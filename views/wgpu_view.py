"""Native Metal input and presentation sharing the document camera and selection."""
import time
import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import QWidget
from core.camera import OrbitCamera
from views.wgpu_scene import pack_scene


class WgpuView(QWidget):
    frameReady = Signal(float, object, float)
    _ZOOM_OUT_STEP = 0.05

    def _model_diag(self):
        return float(np.linalg.norm(self.packed.world_bounds[1]-self.packed.world_bounds[0]))

    def __init__(self, parent=None):
        super().__init__(parent)
        for attr in (Qt.WA_NativeWindow, Qt.WA_PaintOnScreen, Qt.WA_NoSystemBackground):
            self.setAttribute(attr)
        self.camera = OrbitCamera()
        self.source_viewport = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.hovered_row = None
        self.inference_index = None
        self.hover_ms = 0.
        self.selection_ms = 0.
        self._selection_signature = None
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self.update)
        self._last_camera = None
        self.renderer = None
        self.packed = None
        self._scene_dirty = False
        self.overlay_primitives = []
        self.overlay_ms = 0.
        self.last = None
        self.build_seconds = self.upload_seconds = 0.
        from views.wgpu_tools import NativeTools
        self.tools = NativeTools(self)

    def paintEngine(self):
        return None

    def _observe_tool_source(self):
        source = self.source_viewport
        previous = getattr(self, '_tool_source', None)
        if source is previous:
            return
        signal = getattr(previous, 'measurementChanged', None)
        if hasattr(signal, 'disconnect'):
            signal.disconnect(self._schedule_tool_sync)
        self._tool_source = source
        signal = getattr(source, 'measurementChanged', None)
        if hasattr(signal, 'connect'):
            signal.connect(self._schedule_tool_sync)

    def _schedule_tool_sync(self, *_):
        tool = getattr(self.source_viewport, 'active_tool', None)
        reset = self.tools.start_point is not None and getattr(tool, 'start_point', None) is None
        if self.isVisible() and (tool is not self.tools.tool or reset):
            QTimer.singleShot(0, self._sync_tool_dispatch)

    def _sync_tool_dispatch(self):
        if self.isVisible():
            self.tools.sync()
            self.update()

    def hideEvent(self, event):
        self.tools.cancel()
        super().hideEvent(event)

    def set_scene(self, scene):
        self._observe_tool_source()
        self.scene = scene
        allowed = getattr(scene, '_navigator_allowed', None)
        token = (id(scene), scene._bounds_key(),
                 None if allowed is None else frozenset(allowed))
        if token == getattr(self, "_content_token", None):
            self.update()
            return
        previous_token = getattr(self, "_content_token", None)
        self._content_token = token
        start = time.perf_counter()
        tracker = getattr(self, '_instance_updates', None)
        if tracker is not None:
            if previous_token is not None and (previous_token[1][1:], previous_token[2]) != (token[1][1:], token[2]):
                tracker.journal_valid = False
            tracker.observe(getattr(self.source_viewport, 'history', None))
        delta = tracker.diff(scene) if tracker is not None and len(self.packed.instances) else None
        if delta is not None:
            ids, rows = delta
            tracker.apply(ids, rows, self.renderer)
            if len(ids) or tracker.changed or tracker.removed:
                mapping_changed = bool(tracker.removed)
                for row in ids:
                    uid = self.packed.uids[row]
                    if uid not in self.uid_rows:
                        self.uid_rows[uid] = [int(row)]
                        mapping_changed = True
                for row in tracker.removed:
                    self.uid_rows.pop(self.packed.uids[row], None)
                if mapping_changed:
                    self._selection_signature = None
                    self._tint_signature = None
                self._resident_count = len(self.packed.instances)
                if self.inference_index is not None:
                    self.inference_index.update(ids, self.packed,
                                                [code for _, _, code in tracker.changed])
                else:
                    self.inference_index = None
                    previous = getattr(self, '_inference_future', None)
                    if previous is not None:
                        previous.cancel()
                        self._inference_future = None
                    if not getattr(self, '_inference_queued', False):
                        self._inference_queued = True
                        QTimer.singleShot(0, self._refresh_inference)
            self.build_seconds = time.perf_counter() - start
            self.update()
            return
        self.packed = pack_scene(scene, getattr(self.source_viewport, 'view_tint', None))
        self._scene_dirty = True
        self._selection_signature = None
        self._tint_signature = None
        self.uid_rows = {}
        for row, uid in enumerate(self.packed.uids):
            self.uid_rows.setdefault(uid, []).append(row)
        from views.wgpu_updates import InstanceUpdates
        if tracker is not None and tracker.unsubscribe is not None:
            tracker.unsubscribe()
        self._resident_count = len(self.packed.instances)
        self._instance_updates = InstanceUpdates(scene, self.packed)
        self._instance_updates.observe(getattr(self.source_viewport, 'history', None))
        self._prepare_inference()
        self.build_seconds = time.perf_counter()-start
        lo, hi = self.packed.world_bounds
        if self.source_viewport is None:
            self.camera.target = QVector3D(*((lo+hi)/2))
            self.camera.distance = max(float(np.linalg.norm(hi-lo))*1.4, 1.)
        self._upload()

    def _refresh_inference(self):
        self._inference_queued = False
        if getattr(self, "_closed", False):
            return
        self._prepare_inference()

    def _prepare_inference(self):
        from concurrent.futures import ThreadPoolExecutor
        from views.wgpu_inference import prepare
        if not hasattr(self, '_inference_worker'):
            self._inference_worker = ThreadPoolExecutor(max_workers=1)
        previous = getattr(self, '_inference_future', None)
        if previous is not None:
            previous.cancel()
        self.inference_index = None
        self._inference_future = self._inference_worker.submit(prepare, self._inference_snapshot())
    def _inference_snapshot(self):
        from dataclasses import replace
        return replace(self.packed, instances=self.packed.instances.copy(),
                       bounds=self.packed.bounds.copy(), commands=self.packed.commands.copy(),
                       edge_commands=self.packed.edge_commands.copy())

    def _upload(self):
        if self.packed is None or not self.isVisible():
            return
        import ingetrazo_render
        start = time.perf_counter()
        if self.renderer is None:
            self.renderer = ingetrazo_render.Renderer(int(self.winId()), self.width(), self.height(), self.devicePixelRatioF())
        if len(self.packed.instances):
            self.packed.upload(self.renderer)
        else:
            # The renderer ABI requires one row. A hidden scratch row lets
            # an empty document show the first tool rubber band.
            from core.mesh import Mesh
            from core.group import Group
            from core.scene import Scene
            mesh = Mesh()
            mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
            scratch = pack_scene(Scene(groups=[Group(mesh)]))
            scratch.instances['info'][:, 2] = 1
            scratch.upload(self.renderer)
        self._frame_style = None
        self.upload_seconds = time.perf_counter()-start
        self._scene_dirty = False
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.renderer is None or self._scene_dirty:
            self._upload()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.renderer is not None:
            self.renderer.resize(self.width(), self.height(), self.devicePixelRatioF())
        self.update()

    def draw_frame(self):
        if self.renderer is None:
            return None
        start = time.perf_counter()
        self.tools.sync()
        if self.source_viewport is not None:
            self.camera = self.source_viewport.camera
        # R-look 3c: compute each camera matrix once, after updating aspect.
        self.camera.aspect = self.width()/max(1, self.height())
        view = self.camera.view_matrix()
        projection = self.camera.projection_matrix()
        if self.source_viewport is not None:
            style = self.source_viewport._effective_style()
            from views.wgpu_style import style_payload
            mvp = projection * view
            payload = style_payload(
                self.source_viewport.scene, style,
                horizon=self.source_viewport._horizon_ndc_y(mvp),
                scale=self.devicePixelRatioF())
            if payload != getattr(self, '_frame_style', None):
                self.renderer.set_style(payload)
                self._frame_style = payload
            tint = getattr(self.source_viewport, 'view_tint', None) or {}
            context = self.scene.edit_group
            signature = (tuple(sorted(tint.items())), id(context))
            if signature != getattr(self, '_tint_signature', None):
                colors = []
                from core.group import iter_placements
                context_ids = ({id(g) for g, _ in iter_placements(context)}
                               if context is not None else set())
                for uid, group in zip(self.packed.uids, self.packed.groups):
                    rgb = tint.get(uid)
                    if context is not None and id(group) not in context_ids:
                        rgb = (.35, .35, .35)
                    colors.append(int(np.array([*np.clip(np.array(rgb[:3])*255, 0, 255), 255],
                                               np.uint8).view('<u4')[0]) if rgb is not None else 0)
                self.renderer.set_overrides(colors)
                self._tint_signature = signature
        future = getattr(self, '_inference_future', None)
        if future is not None and future.done():
            self.inference_index = future.result()
            self._inference_future = None
        self.sync_selection()
        physical = (self.width(), self.height(), self.devicePixelRatioF())
        if physical != getattr(self, '_physical_size', None):
            self.renderer.resize(*physical)
            self._physical_size = physical
        camera_key = (tuple(view.data()), tuple(projection.data()))
        if camera_key != self._last_camera:
            self._last_camera = camera_key
            self._settle_timer.start(80)
        self.renderer.set_camera(*camera_key)
        # End R-look 3c camera/style work.
        annotations = bool(self.scene.dimensions or self.scene.text_labels)
        if annotations or self.overlay_primitives or getattr(self, "_had_overlay", False):
            from views.wgpu_overlay import rasterize, pixels
            before = time.perf_counter()
            image = rasterize(self.overlay_primitives, self.width(), self.height(), self.devicePixelRatioF(),
                              self.tools.draw_annotations if annotations else None)
            self.renderer.set_overlay(image.width(), image.height(), pixels(image))
            self.overlay_ms = (time.perf_counter() - before) * 1000
            self._had_overlay = annotations or bool(self.overlay_primitives)
        cpu, gpu = self.renderer.render()
        wall = (time.perf_counter()-start)*1000
        self.frameReady.emit(cpu, gpu, wall)
        return cpu, gpu, wall

    def render_image(self, width_px, height_px=None, overlays=False,
                     sharp_shadows=False):
        """Render sheet pixels without touching the interactive GPU or camera.

        A temporary native host owns a separate device and scene upload. It is
        never shown: capture targets the renderer's offscreen texture. Sections
        are not supported by the Metal pipeline yet; fail instead of silently
        printing an uncut model.
        """
        from copy import copy
        from PySide6.QtGui import QImage
        from views.wgpu_style import style_payload
        import ingetrazo_render

        source = self.source_viewport
        if height_px is None:
            height_px = round(width_px * self.height() / max(1, self.width()))
        width_px, height_px = int(width_px), int(height_px)
        if width_px <= 0 or height_px <= 0:
            raise ValueError("Image dimensions must be positive")
        scene = source.scene
        if scene.active_section() is not None and scene.show_section_cuts:
            raise NotImplementedError("Metal sheet section cuts are not implemented")
        camera = copy(source.camera)
        camera.aspect = width_px / height_px
        host = QWidget()
        host.setAttribute(Qt.WA_NativeWindow)
        renderer = None
        try:
            renderer = ingetrazo_render.Renderer(int(host.winId()), width_px, height_px, 1.)
            packed = pack_scene(scene, getattr(source, 'view_tint', None))
            if not len(packed.instances):
                image = QImage(width_px, height_px, QImage.Format_RGBA8888)
                image.fill(QColor.fromRgbF(*source._effective_style().background))
                return image
            packed.upload(renderer)
            view, projection = camera.view_matrix(), camera.projection_matrix()
            payload = style_payload(scene, source._effective_style(),
                                    horizon=source._horizon_ndc_y(projection * view))
            payload['edge_width'] = float(getattr(source, '_export_edge_px', 1))
            payload['profile_width'] = float(getattr(source, '_export_profile_px', 1))
            renderer.set_style(payload)
            renderer.set_camera(tuple(view.data()), tuple(projection.data()))
            renderer.request_capture()
            renderer.render(False)
            pixels = bytes(renderer.take_capture())
            return QImage(pixels, width_px, height_px, width_px * 4,
                          QImage.Format_RGBA8888).copy()
        finally:
            renderer = None
            host.destroy()

    def paintEvent(self, event):
        self.draw_frame()

    def resolve(self, row):
        """The resident row identifies both the placement and shared prototype."""
        if self.packed is None or row is None or not 0 <= row < len(self.packed.uids):
            return None
        if self.packed.instances['info'][row, 2] & 1:
            return None
        return self.packed.groups[row], int(self.packed.instances['info'][row, 0])

    def pick_row(self, x, y):
        if self.renderer is None or x < 0 or y < 0:
            return None
        scale = self.devicePixelRatioF()
        row = self.renderer.pick(int(x*scale), int(y*scale))
        return row if self.resolve(row) is not None else None

    def _pixel_to_ray(self, x, y):
        from views.viewport import Viewport
        return Viewport._pixel_to_ray(self, x, y)

    def _world_to_pixel(self, point):
        from views.viewport import Viewport
        return Viewport._world_to_pixel(self, point)

    def hover(self, x, y, modifiers=Qt.NoModifier):
        from views.wgpu_inference import snap
        from views.wgpu_overlay import snap_glyph, Primitive
        start = time.perf_counter()
        self.hovered_row = self.pick_row(x, y)
        self.last_snap = None
        self.overlay_primitives = []
        source = self.source_viewport
        if self.tools.sync() == 'mesh':
            self.tools.work_point(x, y)
        tool = getattr(source, 'active_tool', None)
        if tool is not None and not tool.uses_snap and self.tools.mode == 'mesh':
            from types import SimpleNamespace
            point = self.tools.work_point(x, y)
            if point is not None:
                self.last_snap = SimpleNamespace(point=point, kind=None, context=None)
            self.update()
            return self.last_snap
        inference = getattr(source, 'inference', None)
        options = dict(start_point=self.tools.start_point,
                       chain_first_point=getattr(tool, 'chain_first_point', None),
                       acquired_point=getattr(inference, '_acquired_point', None),
                       acquired_points=getattr(inference, '_encouraged', None),
                       axis_lock=getattr(inference, 'axis_lock', None),
                       shift_held=bool(modifiers & Qt.ShiftModifier),
                       reference_edge=getattr(inference, 'reference_edge', None),
                       reference_mode=getattr(inference, 'reference_mode', None),
                       magnetic_axis_deg=getattr(tool, 'magnetic_axis_deg', None),
                       screen_axis_px=getattr(tool, 'screen_axis_px', None),
                       linear_mode=getattr(source, 'linear_inference_mode', 'all'),
                       project_onto_line=lambda start, direction:
                           self._project_to_lock_line(start, direction, x, y))
        if self.hovered_row is not None and self.inference_index is not None:
            self.last_snap = snap(self.inference_index, self.hovered_row, self, x, y, **options)
        elif self.tools.sync() in ('tape', 'move', 'mesh'):
            from core.snap import compute_snap
            from types import SimpleNamespace
            origin, direction = self._pixel_to_ray(x, y)
            plane = self.tools.start_point if self.tools.start_point is not None else self.camera.target
            normal = self.camera.forward()
            denominator = QVector3D.dotProduct(direction, normal)
            if abs(denominator) > 1e-9:
                point = origin + direction * (QVector3D.dotProduct(plane-origin, normal)/denominator)
                if self.tools.mode == 'mesh':
                    point = self.tools.work_point(x, y) or point
                self.last_snap = compute_snap(point, (x, y), SimpleNamespace(edges=[]),
                                              self._world_to_pixel, 12., **options)
        if inference is not None and self.last_snap is not None:
            source._note_snap(self.last_snap)
            point = (self.last_snap.point if self.last_snap.kind in source._ENCOURAGING_KINDS else None)
            inference._dwell_on(point)
        if self.last_snap is not None:
            pixel = self._world_to_pixel(self.last_snap.point)
            if pixel is not None:
                self.overlay_primitives.append(snap_glyph(
                    pixel, self.last_snap.kind, QColor.fromRgbF(*self.last_snap.color).name()))
            guides = list(self.last_snap.guides or [])
            if self.last_snap.guide:
                guides.append((*self.last_snap.guide, self.last_snap.color))
            for a, b, color in guides:
                pa, pb = self._world_to_pixel(a), self._world_to_pixel(b)
                if pa is not None and pb is not None:
                    self.overlay_primitives.append(Primitive(
                        'polyline', (pa, pb), QColor.fromRgbF(*color).name()))
        self.sync_selection()
        self.hover_ms = (time.perf_counter()-start)*1000
        from views.viewport import _PERF, _plog
        if _PERF:
            _plog("hover", self.hover_ms, extra="renderer=wgpu id-local", floor=0.)
        self.update()
        return self.last_snap

    def sync_selection(self):
        if self.renderer is None:
            return
        selected = frozenset(getattr(g, 'uid', None) for g in self.scene.selection)
        signature = (selected, self.hovered_row)
        if signature != self._selection_signature:
            indices = [i for uid in selected for i in self.uid_rows.get(uid, ())]
            self.renderer.set_highlight(indices, self.hovered_row)
            self._selection_signature = signature

    def select_rows(self, rows, modifiers=Qt.NoModifier):
        start = time.perf_counter()
        groups = {self.packed.groups[i] for i in rows if self.resolve(i) is not None}
        groups = [g for g in groups if g is not None and self.scene.entity_selectable(g)]
        mode = ('toggle' if modifiers & (Qt.ControlModifier | Qt.MetaModifier)
                else 'add' if modifiers & Qt.ShiftModifier else 'replace')
        self.scene.select(groups, mode=mode)
        self.sync_selection()
        if self.source_viewport is not None:
            self.source_viewport.notify_scene_changed()
        self.update()
        self.selection_ms = (time.perf_counter()-start)*1000

    def mousePressEvent(self, event):
        self.setFocus()
        self.last = self.press = event.position()
        self._drag_nav = event.button() == Qt.MiddleButton or bool(
            getattr(self.source_viewport, 'nav_mode', None))
        mode = self.tools.sync()
        if (not self._drag_nav and callable(getattr(self.tools.tool, 'on_look', None))
                and event.button() in (Qt.LeftButton, Qt.RightButton)):
            from views.viewport import Viewport
            Viewport._begin_look(self, event)
            return
        if not self._drag_nav and event.button() == Qt.LeftButton and mode in ('tape', 'move', 'mesh'):
            self.hover(self.press.x(), self.press.y(), event.modifiers())
            self.tools.click(event)
        if self._drag_nav:
            self._pivot = self._orbit_pivot_at(self.press.x(), self.press.y())

    def mouseMoveEvent(self, event):
        if getattr(self, '_look_drag', None) is not None:
            from views.viewport import Viewport
            if event.buttons():
                Viewport._look_move(self, event)
                return
            self._look_drag = None
            self.tools._apply_tool_cursor()
        if not event.buttons():
            self.last = None
            self.hover(event.position().x(), event.position().y(), event.modifiers())
            self.tools.hover(event)
            return
        if self.last is None:
            return
        delta = event.position().toPoint()-self.last.toPoint()
        self.last = event.position()
        mode = getattr(self.source_viewport, 'nav_mode', None)
        if self._drag_nav and mode != 'zoom_window':
            if mode == 'zoom':
                self.camera.zoom(-delta.y()*.035)
            elif mode == 'pan' or event.modifiers() & Qt.ShiftModifier:
                depth = QVector3D.dotProduct(self._pivot-self.camera.eye(), self.camera.forward())
                self.camera.pan(delta.x(), delta.y(), self.height(), depth=depth)
            else:
                dy = -delta.y() if getattr(self.source_viewport, '_invert_orbit_y', False) else delta.y()
                self.camera.orbit_about(self._pivot, delta.x(), dy, self.height())
        elif self.tools.sync() in ('tape', 'move', 'mesh'):
            self.hover(event.position().x(), event.position().y(), event.modifiers())
            self.tools.hover(event)
        elif event.buttons() & Qt.LeftButton and (self.tools.mode == 'select' or mode == 'zoom_window'):
            from views.wgpu_overlay import Primitive
            self.overlay_primitives = [Primitive('rectangle',
                ((self.press.x(), self.press.y()), (self.last.x(), self.last.y())))]
        self.update()

    @property
    def active_tool(self):
        return self.tools.tool

    def _can_warp_pointer(self):
        from views.viewport import Viewport
        return Viewport._can_warp_pointer()

    def focusOutEvent(self, event):
        self._look_drag = None
        hook = getattr(self.tools.tool, 'on_focus_out', None)
        if hook is not None:
            hook(self.tools)
        self.tools.cancel()
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, '_look_drag', None) is not None:
            self._look_drag = None
            self.tools._apply_tool_cursor()
            self.last = None
            return
        if self.last is None:
            return
        mode = getattr(self.source_viewport, 'nav_mode', None)
        if self._drag_nav:
            if mode == 'zoom_window':
                from views.viewport import Viewport
                Viewport._zoom_to_box(self, self.press, event.position())
        elif event.button() == Qt.LeftButton and self.tools.sync() == 'select':
            start = time.perf_counter()
            annotation = (self.tools.pick_text_label(event.position().x(), event.position().y())
                          or self.tools.pick_dimension(event.position().x(), event.position().y()))
            if annotation is not None and (event.position()-self.press).manhattanLength() < 3:
                selection_mode = ('toggle' if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
                                  else 'add' if event.modifiers() & Qt.ShiftModifier else 'replace')
                self.scene.select([annotation], mode=selection_mode)
                self.source_viewport.notify_scene_changed()
                self.last = None
                self.update()
                return
            if (event.position()-self.press).manhattanLength() < 3:
                row = self.pick_row(event.position().x(), event.position().y())
                rows = [] if row is None else [row]
                resolved = self.resolve(row)
                if resolved is not None and (resolved[0] is self.scene.edit_group or
                        (resolved[0] is None and self.scene.edit_group is None)):
                    entity = (self.tools.pick_visible_edge(event.position().x(), event.position().y())
                              or self.tools.pick_face(event.position().x(), event.position().y()))
                    mode = ('toggle' if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
                            else 'add' if event.modifiers() & Qt.ShiftModifier else 'replace')
                    self.scene.select([] if entity is None else [entity], mode=mode)
                    self.source_viewport.notify_scene_changed()
                    self.last = None
                    self.update()
                    return
            else:
                rows = self.rect_rows(self.press.x(), self.press.y(), event.position().x(), event.position().y())
            self.select_rows(rows, event.modifiers())
            self.selection_ms = (time.perf_counter()-start)*1000
        if self.tools.mode == 'mesh':
            self.tools.tool.on_release(self.tools)
            self.tools.update()
            self.overlay_primitives = []
            self.tools.mesh_feedback()
        self.last = None
        if self.tools.mode == 'select' or mode == 'zoom_window':
            self.overlay_primitives = []
        self.update()

    def mouseDoubleClickEvent(self, event):
        mode = self.tools.sync()
        if mode in ('tape', 'move', 'mesh'):
            self.hover(event.position().x(), event.position().y(), event.modifiers())
            if mode == 'mesh':
                ctx = self.tools.context(event)
                if ctx is not None:
                    self.tools.tool.on_double_click(ctx)
                    self.tools.update()
            else:
                self.tools.click(event)
            return
        if mode != 'select':
            return
        row = self.pick_row(event.position().x(), event.position().y())
        resolved = self.resolve(row)
        if resolved is not None and resolved[0] is not None and self.source_viewport is not None:
            self.source_viewport.begin_group_edit(resolved[0])
            self.source_viewport.notify_scene_changed()
            self.update()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and hasattr(self, 'tools'):
            self.tools.sync()
            claims = getattr(self.tools.tool, 'claims_key', None)
            if claims is not None and claims(event.key(), event.modifiers()):
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event):
        mode = self.tools.sync()
        if event.key() == Qt.Key_Escape:
            self._look_drag = None
            self.tools._apply_tool_cursor()
        if event.key() == Qt.Key_Escape and mode in ('tape', 'move', 'mesh'):
            self.tools.cancel()
        elif event.key() == Qt.Key_Escape:
            if self.scene.edit_group is not None and self.source_viewport is not None:
                self.source_viewport.end_one_group_edit()
                self.source_viewport.notify_scene_changed()
            else:
                self.scene.clear_selection()
            self.last = None
            self.overlay_primitives = []
            self.sync_selection()
        elif self.tools.key(event):
            pass
        elif mode == 'inert':
            event.ignore()
        elif self.source_viewport is not None:
            self.source_viewport.keyPressEvent(event)
        self.update()

    def keyReleaseEvent(self, event):
        mode = self.tools.sync()
        release = getattr(self.tools.tool, 'on_key_release', None)
        if mode == 'mesh' and event.isAutoRepeat() and callable(getattr(self.tools.tool, 'claims_key', None)):
            return
        if mode == 'mesh' and release is not None and release(self.tools, event.key()):
            self.tools.update()
            return
        if mode == 'inert':
            event.ignore()
            return
        if self.source_viewport is not None:
            self.source_viewport.keyReleaseEvent(event)

    def _project_to_lock_line(self, start, direction, x, y):
        from views.viewport import Viewport
        return Viewport._project_to_lock_line(self, start, direction, x, y)

    def _depth_world_at(self, x, y):
        from views.wgpu_inference import surface
        row = self.pick_row(x, y)
        if row is not None and self.inference_index is not None:
            point = surface(self.inference_index, row, *self._pixel_to_ray(x, y))
            if point is not None:
                return 'hit', point
        return 'miss', None

    def _world_under_cursor(self, x, y):
        from views.viewport import Viewport
        return Viewport._world_under_cursor(self, x, y)

    def _orbit_pivot_at(self, x, y):
        from views.viewport import _ray_aabb_span
        seen, point = self._depth_world_at(x, y)
        if seen == 'hit':
            return point
        origin, direction = self._pixel_to_ray(self.width()/2, self.height()/2)
        lo, hi = self.packed.world_bounds
        span = _ray_aabb_span(origin.toTuple(), direction.toTuple(), tuple(lo), tuple(hi))
        if span is not None:
            return origin + direction*((span[0]+span[1])*.5)
        return QVector3D(self.camera.target)

    def _zoom_out_step(self):
        from views.viewport import Viewport
        return Viewport._zoom_out_step(self)

    def wheelEvent(self, event):
        from views.viewport import Viewport
        self._invert_wheel = getattr(self.source_viewport, '_invert_wheel', False)
        Viewport.wheelEvent(self, event)
        self.update()

    def set_highlight(self, selected_ids, hovered_id=None):
        if self.renderer is None:
            return
        indices = [i for uid in selected_ids for i in self.uid_rows.get(uid, ())]
        hover = next(iter(self.uid_rows.get(hovered_id, ())), None)
        self.renderer.set_highlight(indices, hover)
        self.update()

    def rect_rows(self, x0, y0, x1, y1):
        if self.renderer is None:
            return []
        scale = self.devicePixelRatioF()
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return self.renderer.pick_rect(*(max(0, int(v*scale)) for v in (x0, y0, x1, y1)))

    def pick_rect(self, x0, y0, x1, y1):
        return [self.packed.uids[i] for i in self.rect_rows(x0, y0, x1, y1)]

    def closeEvent(self, event):
        self._closed = True
        tracker = getattr(self, '_instance_updates', None)
        if tracker is not None and tracker.unsubscribe is not None:
            tracker.unsubscribe()
        self.renderer = None
        if hasattr(self, '_inference_worker'):
            self._inference_worker.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
