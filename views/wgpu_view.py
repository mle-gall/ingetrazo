"""Native Metal input and presentation sharing the document camera and selection."""
import time
import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer
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

    def paintEngine(self):
        return None

    def set_scene(self, scene):
        self.scene = scene
        allowed = getattr(scene, '_navigator_allowed', None)
        token = (id(scene), scene._bounds_key(),
                 None if allowed is None else frozenset(allowed))
        if token == getattr(self, "_content_token", None):
            self.update()
            return
        self._content_token = token
        start = time.perf_counter()
        self.packed = pack_scene(scene, getattr(self.source_viewport, 'view_tint', None))
        self._scene_dirty = True
        self._selection_signature = None
        self._tint_signature = None
        self.uid_rows = {}
        for row, uid in enumerate(self.packed.uids):
            self.uid_rows.setdefault(uid, []).append(row)
        from concurrent.futures import ThreadPoolExecutor
        from views.wgpu_inference import prepare
        if not hasattr(self, '_inference_worker'):
            self._inference_worker = ThreadPoolExecutor(max_workers=1)
        previous = getattr(self, '_inference_future', None)
        if previous is not None:
            previous.cancel()
        self.inference_index = None
        self._inference_future = self._inference_worker.submit(prepare, self.packed)
        self.build_seconds = time.perf_counter()-start
        lo, hi = self.packed.world_bounds
        if self.source_viewport is None:
            self.camera.target = QVector3D(*((lo+hi)/2))
            self.camera.distance = max(float(np.linalg.norm(hi-lo))*1.4, 1.)
        self._upload()

    def _upload(self):
        if self.packed is None or not self.isVisible():
            return
        import ingetrazo_render
        start = time.perf_counter()
        if self.renderer is None:
            self.renderer = ingetrazo_render.Renderer(int(self.winId()), self.width(), self.height(), self.devicePixelRatioF())
        if len(self.packed.instances):
            self.packed.upload(self.renderer)
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
        if self.renderer is None or not len(self.packed.instances):
            return None
        start = time.perf_counter()
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
        if self.overlay_primitives or getattr(self, "_had_overlay", False):
            from views.wgpu_overlay import rasterize, pixels
            before = time.perf_counter()
            image = rasterize(self.overlay_primitives, self.width(), self.height(), self.devicePixelRatioF())
            self.renderer.set_overlay(image.width(), image.height(), pixels(image))
            self.overlay_ms = (time.perf_counter() - before) * 1000
            self._had_overlay = bool(self.overlay_primitives)
        cpu, gpu = self.renderer.render()
        wall = (time.perf_counter()-start)*1000
        self.frameReady.emit(cpu, gpu, wall)
        return cpu, gpu, wall

    def paintEvent(self, event):
        self.draw_frame()

    def resolve(self, row):
        """The resident row identifies both the placement and shared prototype."""
        if self.packed is None or row is None or not 0 <= row < len(self.packed.uids):
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
        if self.hovered_row is not None and self.inference_index is not None:
            source = self.source_viewport
            tool = getattr(source, 'active_tool', None)
            inference = getattr(source, 'inference', None)
            self.last_snap = snap(self.inference_index, self.hovered_row, self, x, y,
                                  start_point=getattr(tool, 'start_point', None),
                                  acquired_point=getattr(inference, '_acquired_point', None),
                                  acquired_points=getattr(inference, '_encouraged', None),
                                  axis_lock=getattr(inference, 'axis_lock', None),
                                  shift_held=bool(modifiers & Qt.ShiftModifier),
                                  reference_edge=getattr(inference, 'reference_edge', None),
                                  reference_mode=getattr(inference, 'reference_mode', None),
                                  linear_mode=getattr(source, 'linear_inference_mode', 'all'),
                                  project_onto_line=lambda start, direction:
                                      self._project_to_lock_line(start, direction, x, y))
            if inference is not None:
                source._note_snap(self.last_snap)
                point = (self.last_snap.point if self.last_snap is not None
                         and self.last_snap.kind in source._ENCOURAGING_KINDS else None)
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
        if self._drag_nav:
            self._pivot = self._orbit_pivot_at(self.press.x(), self.press.y())

    def mouseMoveEvent(self, event):
        if not event.buttons():
            self.last = None
            self.hover(event.position().x(), event.position().y(), event.modifiers())
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
        elif event.buttons() & Qt.LeftButton:
            from views.wgpu_overlay import Primitive
            self.overlay_primitives = [Primitive('rectangle',
                ((self.press.x(), self.press.y()), (self.last.x(), self.last.y())))]
        self.update()

    def mouseReleaseEvent(self, event):
        if self.last is None:
            return
        mode = getattr(self.source_viewport, 'nav_mode', None)
        if self._drag_nav:
            if mode == 'zoom_window':
                from views.viewport import Viewport
                Viewport._zoom_to_box(self, self.press, event.position())
        elif event.button() == Qt.LeftButton:
            start = time.perf_counter()
            if (event.position()-self.press).manhattanLength() < 3:
                row = self.pick_row(event.position().x(), event.position().y())
                rows = [] if row is None else [row]
            else:
                rows = self.rect_rows(self.press.x(), self.press.y(), event.position().x(), event.position().y())
            self.select_rows(rows, event.modifiers())
            self.selection_ms = (time.perf_counter()-start)*1000
        self.last = None
        self.overlay_primitives = []
        self.update()

    def mouseDoubleClickEvent(self, event):
        row = self.pick_row(event.position().x(), event.position().y())
        resolved = self.resolve(row)
        if resolved is not None and resolved[0] is not None and self.source_viewport is not None:
            self.source_viewport.begin_group_edit(resolved[0])
            self.source_viewport.notify_scene_changed()
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.scene.edit_group is not None and self.source_viewport is not None:
                self.source_viewport.end_one_group_edit()
                self.source_viewport.notify_scene_changed()
            else:
                self.scene.clear_selection()
            self.last = None
            self.overlay_primitives = []
            self.sync_selection()
        elif self.source_viewport is not None:
            self.source_viewport.keyPressEvent(event)
        self.update()

    def keyReleaseEvent(self, event):
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
        self.renderer = None
        if hasattr(self, '_inference_worker'):
            self._inference_worker.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
