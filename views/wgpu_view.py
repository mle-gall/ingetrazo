"""Native Metal input and presentation sharing the document camera and selection."""
import time
import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtWidgets import QWidget
from core.camera import OrbitCamera
from views.wgpu_scene import pack_scene
from tools.select import selection_mode


def _paint_key(scene):
    """What the baked paint depends on besides the content: Colour by
    tag (with a style that shows it), and each tag's colour, opacity and
    lock — what ``views.viewport._paint_of`` reads for a container."""
    style = getattr(scene, 'display_style', None)
    by_layer = (bool(getattr(style, 'color_by_layer', False))
                and getattr(style, 'face_mode', None) in ('textures', 'shaded', 'xray'))
    from core.layers import layer_color
    return (by_layer, bool(getattr(scene, 'show_hidden_geometry', False)),
            bool(getattr(scene, 'show_hidden_objects', False)), tuple(
        (ly.name, tuple(layer_color(ly)) if by_layer else None,
         float(getattr(ly, 'opacity', 1.0)), bool(getattr(ly, 'locked', False)))
        for ly in getattr(scene, 'layers', ())))


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
        version, stack, _, similar, layers = scene._bounds_key()
        token = (id(scene), (version - scene._placement_context_bumps,
                             stack if similar else (), similar, layers),
                 None if allowed is None else frozenset(allowed))
        paint_key = _paint_key(scene)
        resident_copies = getattr(self, '_resident_edit_copies', ())
        sharing_restored = any(group.mesh is not mesh for group, mesh in resident_copies)
        if (not sharing_restored and token == getattr(self, "_content_token", None)
                and paint_key == getattr(self, "_paint_key", None)):
            tracker = getattr(self, '_instance_updates', None)
            if tracker is not None:
                tracker.version = version  # only the context bump was skipped
            self.update()
            return
        if getattr(self, "_billboards", None) is not None:
            self._billboards.restore()
        previous_token = getattr(self, "_content_token", None)
        # Colour by tag toggled, or a tag's colour or look changed: the
        # per-face colours are baked into the resident vertices, so the
        # scene packs again (the row delta below only moves placements).
        repaint = paint_key != getattr(self, "_paint_key", None)
        self._resident_edit_copies = [(level['group'], level['world_copy'])
                                      for level in scene._edit_stack if level.get('world_copy')]
        self._selection_rows = {}
        self._selection_signature = None
        self._container_boxes = {}
        self._pick_frame_dirty = True
        start = time.perf_counter()
        tracker = getattr(self, '_instance_updates', None)
        if tracker is not None:
            visibility_changed = previous_token is not None and (
                previous_token[1][1:] != token[1][1:] or previous_token[2] != token[2])
            if sharing_restored or visibility_changed:
                tracker.journal_valid = False
            tracker.observe(getattr(self.source_viewport, 'history', None))
        delta = (tracker.diff(scene) if tracker is not None and len(self.packed.instances)
                 and not repaint else None)
        if delta is not None:
            ids, rows = delta
            tracker.apply(ids, rows, self.renderer)
            from views.wgpu_parity import hidden_geometry, face_ranges
            if tracker.changed:
                self.packed.__dict__.pop("_face_ranges", None)
                self._selection_signature = None
                if getattr(self, 'suppressed_faces', ()) and self.renderer is not None:
                    self.renderer.set_suppressed_faces(face_ranges(self, self.suppressed_faces))
            hidden_geometry(self)
            self._rest_signature = None
            from views.wgpu_billboards import Billboards
            self._billboards = Billboards(self.packed)
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
            self._content_token = token
            self._paint_key = paint_key
            self.build_seconds = time.perf_counter() - start
            self.update()
            return
        self.packed = pack_scene(scene, getattr(self.source_viewport, 'view_tint', None))
        from views.wgpu_billboards import Billboards
        self._billboards = Billboards(self.packed)
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
        # Compute expensive edit boxes in the load pass. The world geometry
        # and the group's own axes survive entering/leaving a container.
        if len(self.packed.instances) > 4096:
            from views.viewport import Viewport
            for group in scene.groups:
                if group.children and len(self._rows_for_group(group)) > 4096:
                    self._container_boxes[group] = Viewport._compute_obb(group)
        self._prepare_inference()
        self.build_seconds = time.perf_counter()-start
        lo, hi = self.packed.world_bounds
        if self.source_viewport is None:
            self.camera.target = QVector3D(*((lo+hi)/2))
            self.camera.distance = max(float(np.linalg.norm(hi-lo))*1.4, 1.)
        self._upload()
        self._content_token = token
        self._paint_key = paint_key

    def blank(self):
        """Only the background, while another document loads into this
        view: the previous model stayed on screen until the new pack went
        up, which on a big file is a minute after its tab took the name."""
        from core.scene import Scene
        tracker = getattr(self, '_instance_updates', None)
        if tracker is not None and tracker.unsubscribe is not None:
            tracker.unsubscribe()
        self._instance_updates = None
        self._container_boxes = {}
        self._selection_rows = {}
        self._resident_edit_copies = ()
        self._parent_map = None
        self.packed = pack_scene(Scene())
        from views.wgpu_billboards import Billboards
        self._billboards = Billboards(self.packed)
        self._content_token = None
        self._selection_signature = None
        self._tint_signature = None
        self.uid_rows = {}
        self.inference_index = None
        self._scene_dirty = True
        self._upload()
        self.update()

    def _refresh_inference(self):
        self._inference_queued = False
        if getattr(self, "_closed", False):
            return
        self._prepare_inference()

    def _prepare_inference(self):
        if getattr(self, '_closed', False):
            return
        from concurrent.futures import ThreadPoolExecutor
        from views.wgpu_inference import prepare
        if not hasattr(self, '_inference_worker'):
            self._inference_worker = ThreadPoolExecutor(max_workers=1)
        previous = getattr(self, '_inference_future', None)
        if previous is not None:
            previous.cancel()
        self.inference_index = None
        packed = self._inference_snapshot()
        scene = self.scene
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        width, height = self.width(), self.height()

        def build():
            index = prepare(packed, scene)
            if len(packed.instances):
                from views.wgpu_inference import screen_boxes
                # Use the immutable placement and camera snapshots. A resize,
                # orbit or edit before publication invalidates the usual key.
                screen_boxes(index, packed, mvp, width, height)
            return index

        self._inference_future = self._inference_worker.submit(build)

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
        self._resident_count = len(self.packed.instances) or 1
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
        if getattr(self, 'suppressed_faces', ()):
            from views.wgpu_parity import face_ranges
            self.renderer.set_suppressed_faces(face_ranges(self, self.suppressed_faces))
        self._rest_signature = None
        self._frame_style = None
        self._axes_state = None
        if getattr(self, "_billboards", None) is not None:
            self._billboards.key = None
        self.upload_seconds = time.perf_counter()-start
        self._scene_dirty = False
        self._pick_frame_dirty = True
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
        if self.renderer is None or getattr(self, '_drawing_frame', False):
            return None
        self._drawing_frame = True
        try:
            return self._present_frame()
        finally:
            self._drawing_frame = False

    def _present_frame(self):
        start = time.perf_counter()
        # A scene packed since the last frame goes up BEFORE anything is
        # written per instance: the override write below is sized by the
        # new pack, and the renderer rejected it against the old resident
        # scene («one override per instance required») on every frame, so
        # the previous document stayed on screen and the first-frame hook
        # never fired (a new document never finished laying out its trays).
        if self._scene_dirty:
            self._upload()
            if self.renderer is None:
                return None
        self.tools.sync()
        if self.source_viewport is not None:
            self.camera = self.source_viewport.camera
            self._mirror_cursor()
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
                scale=self.devicePixelRatioF(),
                edit_rest_fade=getattr(self.source_viewport, 'edit_rest_fade', .75))
            if payload != getattr(self, '_frame_style', None):
                self.renderer.set_style(payload)
                self._frame_style = payload
            tint = getattr(self.source_viewport, 'view_tint', None) or {}
            signature = tuple(sorted(tint.items()))
            if signature != getattr(self, '_tint_signature', None):
                colors = []
                for uid, group in zip(self.packed.uids, self.packed.groups):
                    rgb = tint.get(uid)
                    colors.append(int(np.array([*np.clip(np.array(rgb[:3])*255, 0, 255), 255],
                                               np.uint8).view('<u4')[0]) if rgb is not None else 0)
                if len(colors) == getattr(self, '_resident_count', None):
                    self.renderer.set_overrides(colors)
                    self._tint_signature = signature
        future = getattr(self, '_inference_future', None)
        if future is not None and future.done():
            self.inference_index = future.result()
            if getattr(self, "_billboards", None) is not None:
                self._billboards.key = None
            self._inference_future = None
        self.sync_edit_context()
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
        if getattr(self, '_billboards', None) is not None:
            self._billboards.update(self.camera, self.renderer, self.inference_index)
        from views.wgpu_axes import axes_state
        axes = axes_state(self.scene, self.camera, self.source_viewport)
        if axes != getattr(self, '_axes_state', None):
            self.renderer.set_axes(*axes)
            self._axes_state = axes
        # End R-look 3c camera/style work.
        # Guides and tool-owned overlays exist without dimensions or labels.
        annotations = self.source_viewport is not None
        # R3c-2a: section widgets share GL's painter implementation.
        from views.wgpu_sections import sync
        sync(self)
        section_widgets = bool(getattr(self.scene, 'section_planes', ())) and getattr(self.scene, 'show_section_planes', True)
        if self.tools.mode == 'mesh' and not self.overlay_primitives:
            self.tools.mesh_feedback()
        primitives = self._edit_box_primitives() + self.overlay_primitives
        if annotations or primitives or section_widgets or getattr(self, "_had_overlay", False):
            from views.wgpu_overlay import rasterize, pixels
            before = time.perf_counter()
            image = rasterize(primitives, self.width(), self.height(), self.devicePixelRatioF(),
                              self.tools.draw_annotations if annotations else None)
            if section_widgets:
                self._paint_section_widgets(image)
            self.renderer.set_overlay(image.width(), image.height(), pixels(image))
            self.overlay_ms = (time.perf_counter() - before) * 1000
            self._had_overlay = annotations or bool(primitives) or section_widgets
        # End R3c-2a section widgets.
        cpu, gpu = self.renderer.render()
        self._pick_frame_dirty = False
        wall = (time.perf_counter()-start)*1000
        self.frameReady.emit(cpu, gpu, wall)
        return cpu, gpu, wall

    def _paint_section_widgets(self, image):
        """R3c-2a: reuse GL's frame, brackets and symbols at Metal's size."""
        from types import SimpleNamespace
        from PySide6.QtGui import QPainter
        from views.viewport import Viewport
        context = SimpleNamespace(scene=self.scene, camera=self.camera,
                                  width=self.width, height=self.height)
        context.section_plane_frame = lambda sp: Viewport.section_plane_frame(context, sp)
        context._clip_segment_front = lambda a, b: Viewport._clip_segment_front(context, a, b)
        context._world_to_pixel = lambda p: Viewport._world_to_pixel(context, p)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            Viewport._draw_section_planes(context, painter)
        finally:
            painter.end()

    def render_image(self, width_px, height_px=None, overlays=False,
                     sharp_shadows=False):
        """R3c-2a: render sheet targets using this view's resident scene."""
        from copy import copy
        from PySide6.QtGui import QImage
        from views.wgpu_style import style_payload

        source = self.source_viewport
        self.tools.sync()
        if height_px is None:
            height_px = round(width_px * self.height() / max(1, self.width()))
        width_px, height_px = int(width_px), int(height_px)
        if width_px <= 0 or height_px <= 0:
            raise ValueError("Image dimensions must be positive")
        if self.renderer is None:
            import ingetrazo_render
            self.renderer = ingetrazo_render.Renderer(
                int(self.winId()), max(1, self.width()), max(1, self.height()), 1.)
            if self.packed is None:
                self.packed = pack_scene(source.scene, getattr(source, 'view_tint', None))
            self.packed.upload(self.renderer)
            self._scene_dirty = False
        elif self._scene_dirty:
            self._upload()
        camera = copy(source.camera)
        camera.aspect = width_px / height_px
        view, projection = camera.view_matrix(), camera.projection_matrix()
        payload = style_payload(source.scene, source._effective_style(),
                                horizon=source._horizon_ndc_y(projection * view),
                                edit_rest_fade=getattr(source, 'edit_rest_fade', .75))
        payload['edge_width'] = float(getattr(source, '_export_edge_px', 1))
        payload['profile_width'] = float(getattr(source, '_export_profile_px', 1))
        from views.wgpu_sections import capture_rows, geometry
        rows = capture_rows(self.packed, source.scene, getattr(source, 'view_tint', None))
        from views.wgpu_edit_context import rest_rows
        mode = getattr(source, 'edit_rest_mode', 'fade')
        rows['info'][:, 2] &= np.uint32(~192 & 0xffffffff)
        if mode in ('fade', 'hide'):
            rows['info'][rest_rows(self.packed.groups, source.scene.edit_group), 2] |= (
                64 | (128 if mode == 'hide' else 0))
        from views.wgpu_billboards import Billboards
        from views.wgpu_axes import axes_state
        capture = copy(self.packed)
        capture.instances = rows
        billboards = getattr(self, '_billboards', None)
        if billboards is not None:
            rows['world'][billboards.ids] = billboards.base
        Billboards(capture).update(camera)
        # Capture rows may change tint/visibility only. Install the camera-facing
        # matrices through the resident API, restoring them even on failure.
        billboard_ids = [] if billboards is None else billboards.ids.tolist()
        resident_world = self.packed.instances['world'][billboard_ids].copy()
        old_axes = getattr(self, '_axes_state', None) or axes_state(source.scene, self.camera, source)
        previous = getattr(self, '_section_uploaded', np.empty(0, np.uint8))
        data = geometry(self, source.scene, source._effective_style(), camera, height_px, rows)
        try:
            if billboard_ids:
                self.renderer.set_instance_world(billboard_ids, rows['world'][billboard_ids].reshape(-1))
            self.renderer.set_axes(*axes_state(source.scene, camera, source))
            self.renderer.set_section_geometry(data)
            pixels = bytes(self.renderer.render_image(
                width_px, height_px, tuple(view.data()), tuple(projection.data()), payload,
                rows.view(np.uint8).reshape(-1)))
        finally:
            if billboard_ids:
                self.renderer.set_instance_world(billboard_ids, resident_world.reshape(-1))
            self.renderer.set_axes(*old_axes)
            self.renderer.set_section_geometry(previous)
        image = QImage(pixels, width_px, height_px, width_px * 4,
                       QImage.Format_RGBA8888).copy()
        if overlays:
            from views.wgpu_annotations import composite_annotations
            image = composite_annotations(image, source.scene, camera,
                logical_size=(self.width(), self.height()), overlays=True)
        return image
        # End R3c-2a offscreen entry point.

    def paintEvent(self, event):
        self.draw_frame()

    def resolve(self, row):
        """The resident row identifies both the placement and shared prototype."""
        if self.packed is None or row is None or not 0 <= row < len(self.packed.uids):
            return None
        if self.packed.instances['info'][row, 2] & 129:
            return None
        return self.packed.groups[row], int(self.packed.instances['info'][row, 0])

    def _prepare_pick_frame(self):
        if getattr(self, '_drawing_frame', False):
            return  # overlay occlusion reads IDs during this very presentation
        if self._scene_dirty and self.isVisible():
            self._upload()
        timer = getattr(self, '_refresh_timer', None)
        if timer is not None and timer.isActive():
            self.set_scene(self.scene)
        self.sync_edit_context()
        if getattr(self, '_pick_frame_dirty', False) and hasattr(self.renderer, 'render'):
            self.draw_frame()

    def pick_row(self, x, y):
        if self.renderer is None or x < 0 or y < 0:
            return None
        self._prepare_pick_frame()
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
        self.tools.sync()
        # Select's priority walk already queries the row for its group pick.
        self.hovered_row = None
        selecting = self.tools.mode == 'select' and not getattr(self.source_viewport, 'nav_mode', None)
        if not selecting or self.source_viewport is None:
            self.hovered_row = self.pick_row(x, y)
        self.hover_rows = ()  # GL paints hovered edges and annotations only.
        self.last_snap = None
        self.overlay_primitives = []
        source = self.source_viewport
        if selecting:
            from tools.select import SelectTool
            from core.mesh import Face
            entity = SelectTool()._pick(self.tools, x, y) if source is not None else None
            self.tools.set_hover(None if isinstance(entity, Face) else entity)
            self.hover_ms = (time.perf_counter()-start)*1000
            self.update()
            return None
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
        if self.inference_index is not None:
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
        self.sync_selection()
        self.hover_ms = (time.perf_counter()-start)*1000
        from views.viewport import _PERF, _plog
        if _PERF:
            _plog("hover", self.hover_ms, extra="renderer=wgpu id-local", floor=0.)
        self.update()
        return self.last_snap

    def sync_edit_context(self):
        if self.renderer is None or self.packed is None:
            return
        mode = getattr(self.source_viewport, 'edit_rest_mode', 'fade')
        signature = (id(self.packed), id(self.scene.edit_group), mode)
        if signature == getattr(self, '_rest_signature', None):
            return
        from views.wgpu_edit_context import rest_rows
        rows = rest_rows(self.packed.groups, self.scene.edit_group)
        before = time.perf_counter()
        if rows or getattr(self, '_rest_signature', None) is not None:
            self.renderer.set_rest(rows, mode)
        self.rest_write_ms = (time.perf_counter() - before) * 1000
        flags = self.packed.instances['info'][:, 2]
        flags &= np.uint32(~(64 | 128) & 0xffffffff)
        if mode in ('fade', 'hide'):
            flags[rows] |= np.uint32(64 | (128 if mode == 'hide' else 0))
        self._pick_frame_dirty = True
        self._rest_signature = signature
        from views.wgpu_parity import hidden_geometry
        hidden_geometry(self)

    def _group_obb(self, group):
        from views.viewport import Viewport
        boxes = self.__dict__.setdefault('_container_boxes', {})
        if group not in boxes:
            boxes[group] = Viewport._compute_obb(group)
        return boxes[group]

    def _edit_group_box_corners(self):
        from views.viewport import Viewport
        return Viewport._edit_group_box_corners(self)

    def edit_group_box_contains_pixel(self, x, y):
        from views.viewport import Viewport
        return Viewport.edit_group_box_contains_pixel(self, x, y)

    def _leave_edit_on_empty_click(self, x, y, modifiers):
        if (self.scene.edit_group is not None and not self.scene.selection
                and not modifiers & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)
                and not self.edit_group_box_contains_pixel(x, y)):
            self.source_viewport.end_one_group_edit()
            self.update()
            return True
        return False

    def _edit_box_primitives(self):
        from views.wgpu_edit_context import box_primitives
        return box_primitives(self)

    def sync_selection(self):
        if self.renderer is None:
            return
        from core.mesh import Face, Edge
        from core.group import Group
        from views.wgpu_parity import face_marks
        selected = self.scene.selection
        hover = tuple(getattr(self, 'hover_rows', ()) or ())
        faces = [f for f in selected if isinstance(f, Face)]
        hovered = getattr(self.tools, '_mesh_hover', getattr(self.source_viewport, '_hover_entity', None))
        signature = (frozenset(map(id, selected)), hover, id(hovered), id(self.packed),
                     tuple(self.camera.eye().toTuple()) if faces else ())
        if signature != self._selection_signature:
            indices = set()
            for root in selected:
                if isinstance(root, Group):
                    indices.update(self._rows_for_group(root))
            self.renderer.set_highlight(list(indices), list(hover))
            if hasattr(self.renderer, 'set_face_marks'):
                self.renderer.set_face_marks(face_marks(self, faces))
            if self.tools.mode == 'select' and hasattr(self.renderer, 'set_preview_mesh'):
                from views.wgpu_scene import VERTEX
                from views.wgpu_parity import raw
                edges = [(e, (.95, .45, .16)) for e in selected if isinstance(e, Edge)]
                if isinstance(hovered, Edge) and hovered not in selected:
                    edges.append((hovered, (.30, .55, .95)))
                vertices = [(p.toTuple(), (0,0,1), (*np.asarray(np.array(c)*255, np.uint8),255))
                            for e,c in edges for p in (e.a,e.b)]
                self.renderer.set_preview_mesh(np.empty(0,np.uint8), raw(np.array(vertices,VERTEX)))
            self._selection_signature = signature

    def _draw_selection_marks(self, painter):
        """Loose edge feedback; faces/groups are depth-tested native passes."""
        if self.tools.mode == 'select' and hasattr(self.renderer, 'set_preview_mesh'):
            return
        from core.mesh import Edge
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen
        entities = [(e, False) for e in self.scene.selection if isinstance(e, Edge)]
        hovered = getattr(self.tools, '_mesh_hover', getattr(self.source_viewport, '_hover_entity', None))
        if isinstance(hovered, Edge) and hovered not in self.scene.selection:
            entities.append((hovered, True))
        painter.save()
        try:
            for edge, hover in entities:
                painter.setPen(QPen(QColor.fromRgbF(*((.30, .55, .95) if hover else (.95, .45, .16))), 1.5))
                a, b = self._world_to_pixel(edge.a), self._world_to_pixel(edge.b)
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))
        finally:
            painter.restore()

    def _mirror_cursor(self):
        """Wear the cursor the tools set on the (hidden) GL viewport: the
        tool icons, Orbit's and Pan's hands, a tool's own changes while it
        works. Copying it once per tool change missed every other change
        (Orbit chosen over Select kept the arrow, Maxence 2026-11-09)."""
        source = self.source_viewport
        if source is None:
            return
        if not source.testAttribute(Qt.WA_SetCursor):
            key = None
        else:
            cur = source.cursor()
            key = (cur.shape(),
                   cur.pixmap().cacheKey() if cur.shape() == Qt.BitmapCursor else 0)
        if key == getattr(self, '_cursor_key', object()):
            return
        self._cursor_key = key
        if key is None:
            self.unsetCursor()
        else:
            self.setCursor(source.cursor())

    def _parents(self):
        """``{id(child): parent}`` over the scene's groups, per pack."""
        token = getattr(self, '_content_token', None)
        cached = getattr(self, '_parent_map', None)
        if cached is not None and cached[0] == token:
            return cached[1]
        parents = {}
        todo = list(self.scene.groups)
        while todo:
            g = todo.pop()
            for child in getattr(g, 'children', None) or ():
                parents[id(child)] = g
                todo.append(child)
        self._parent_map = (token, parents)
        return parents

    def context_placement(self, group):
        """The placement a click selects for a hit on ``group``: the
        top-level object at the root, the child directly under the group
        being edited inside one, ``None`` for a hit outside the context —
        what the GL viewport's ``pick_group`` returns."""
        if group is None:
            return None
        parents = self._parents()
        chain = [group]
        while (parent := parents.get(id(chain[-1]))) is not None:
            chain.append(parent)
        ctx = self.scene.edit_group
        if ctx is None:
            return chain[-1]
        for i, g in enumerate(chain):
            if g is ctx:
                return chain[i-1] if i > 0 else None
        return None

    def _rows_for_group(self, group):
        cache = self.__dict__.setdefault('_selection_rows', {})
        if group not in cache:
            rows = []
            pending = [group]
            while pending:
                child = pending.pop()
                rows.extend(self.uid_rows.get(child.uid, ()))
                pending.extend(child.children or ())
            cache[group] = rows
        return cache[group]

    def select_rows(self, rows, modifiers=Qt.NoModifier):
        start = time.perf_counter()
        groups = {self.context_placement(self.packed.groups[i])
                  for i in rows if self.resolve(i) is not None}
        groups = [g for g in groups if g is not None and self.scene.entity_selectable(g)]
        mode = selection_mode(modifiers)
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
            from views import wgpu_overlay
            primitive = wgpu_overlay.selection_rectangle((self.press.x(), self.press.y()),
                (self.last.x(), self.last.y()), zoom=mode == 'zoom_window')
            self.overlay_primitives = [primitive]
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
            from tools.select import SelectTool
            from tools.base import ToolContext
            tool = self.tools.tool or SelectTool()
            end = event.position()
            if (end-self.press).manhattanLength() < 3:
                tool.on_click(ToolContext(self.tools, QVector3D(), end, event.modifiers(), None))
            else:
                rect = (min(self.press.x(), end.x()), min(self.press.y(), end.y()),
                        max(self.press.x(), end.x()), max(self.press.y(), end.y()))
                tool.on_box_select(self.tools, rect, end.x() < self.press.x(),
                                   mode=selection_mode(event.modifiers()))
            if self.source_viewport is not None:
                self.source_viewport.notify_scene_changed()
            self.sync_selection()
        if self.tools.mode == 'mesh':
            self.tools.tool.on_release(self.tools)
            self.tools.update()
            self.overlay_primitives = []
            self.tools.mesh_feedback()
        self.last = None
        if self.tools.mode == 'select' or mode == 'zoom_window':
            self.overlay_primitives = []
        self.update()

    def contextMenuEvent(self, event):
        self.tools.sync()
        tool = self.tools.tool
        menu = getattr(tool, 'context_menu', None)
        if menu is not None and menu(self.tools, event.globalPos()):
            return
        source = self.source_viewport
        if source is None:
            return
        point = event.pos()
        source._context_pixel = (point.x(), point.y())
        picked = self.tools._context_pick(point.x(), point.y())
        under = self.tools.pick_locked_image_plane(point.x(), point.y())
        window = source.window()
        window.show_viewport_context_menu(
            event.globalPos(), locked_image=under if under is not picked else None,
            locked_group=self.tools.pick_locked_group(point.x(), point.y()))

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
        from tools.select import SelectTool
        from tools.base import ToolContext
        (self.tools.tool or SelectTool()).on_double_click(ToolContext(
            self.tools, QVector3D(), event.position(), event.modifiers(), None))
        self.update()

    def event(self, event):
        if event.type() == QEvent.NativeGesture:
            # Pinch, smart zoom: a trackpad's, or the touch screen's (#248).
            from views import trackpad_nav
            if trackpad_nav.native_gesture(self, event):
                return True
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

    def _zoom_at(self, steps, pos):
        from views.viewport import Viewport
        self._invert_wheel = getattr(self.source_viewport, '_invert_wheel', False)
        return Viewport._zoom_at(self, steps, pos)

    def wheelEvent(self, event):
        from views.viewport import Viewport
        self._invert_wheel = getattr(self.source_viewport, '_invert_wheel', False)
        Viewport.wheelEvent(self, event)
        self.update()

    def set_highlight(self, selected_ids, hovered_id=None):
        if self.renderer is None:
            return
        indices = [i for uid in selected_ids for i in self.uid_rows.get(uid, ())]
        self.renderer.set_highlight(indices, list(self.uid_rows.get(hovered_id, ())))
        self.update()

    def rect_rows(self, x0, y0, x1, y1):
        if self.renderer is None:
            return []
        scale = self.devicePixelRatioF()
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        self._prepare_pick_frame()
        return [row for row in self.renderer.pick_rect(*(max(0, int(v*scale)) for v in (x0, y0, x1, y1)))
                if self.resolve(row) is not None]

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
