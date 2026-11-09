"""Native tool dispatch shares measurement and History semantics with GL.

Live placement moves alter resident matrices only; the document is touched
once, by the same commands used by MoveTool, after the user commits.
"""
import numpy as np
from PySide6.QtCore import Qt
from core.history import MoveGroupCommand, CompoundCommand
from tools.base import ToolContext
from tools.tape import TapeMeasureTool
from views.wgpu_overlay import Primitive

TOOL_DISPATCH = {'SelectTool': 'select',
 'TapeMeasureTool': 'tape',
 'MoveTool': 'move',
 'SectionPlaneTool': 'mesh',
 'LineTool': 'mesh',
 'RectangleTool': 'mesh',
 'PushPullTool': 'mesh',
 'EraserTool': 'mesh',
 'RotateTool': 'mesh',
 'ScaleTool': 'mesh',
 'OffsetTool': 'mesh',
 'CircleTool': 'mesh',
 'PolygonTool': 'mesh',
 'ArcTool': 'mesh',
 'PaintTool': 'mesh',
 'TexturePositionTool': 'mesh',
 'DimensionTool': 'mesh',
 'TextTool': 'mesh',
 'FollowMeTool': 'mesh',
 'FreehandTool': 'mesh',
 'RotatedRectangleTool': 'mesh',
 'ThreePointArcTool': 'mesh',
 'CenterArcTool': 'mesh',
 'PieTool': 'mesh',
 'FlipTool': 'mesh',
 'FilletTool': 'mesh',
 'ProtractorTool': 'mesh',
 'GeoPathTool': 'mesh',
 'ChangeAxesTool': 'mesh',
 'ScaleManagerTool': 'mesh',
 'PositionCameraTool': 'mesh',
 'WalkTool': 'mesh',
 'LookAroundTool': 'mesh',
 'FirstPersonTool': 'mesh',
 'OuterShellTool': 'mesh',
 'UnionTool': 'mesh',
 'SubtractTool': 'mesh',
 'TrimTool': 'mesh',
 'IntersectTool': 'mesh',
 'SplitTool': 'mesh'}


def move_command(groups, delta):
    commands = [MoveGroupCommand(group, delta) for group in groups]
    return commands[0] if len(commands) == 1 else CompoundCommand(commands)


from views.wgpu_mesh_tools import MeshToolAccess


class NativeTools(MeshToolAccess):
    def __init__(self, view):
        self.view = view
        self.tool = None
        self.mode = 'select'
        self.start_point = None
        self.hover_point = None
        self.ids = np.empty(0, np.int64)
        self.original = None
        self.groups = []
        self.value_buffer = ""

    @property
    def scene(self):
        return getattr(self.view, 'scene', None) or getattr(self.view.source_viewport, 'scene', None)

    @property
    def last_snap(self):
        return getattr(self.view, 'last_snap', None)

    @property
    def active_tool(self):
        return self.tool

    def sync(self):
        source = self.view.source_viewport
        tool = getattr(source, 'active_tool', None)
        if tool is self.tool:
            if self.mode in ('tape', 'move') and self.start_point is not None and getattr(tool, 'start_point', None) is None:
                self.cancel()
            return self.mode
        preview = getattr(self.view, '_texture_preview', None)
        if preview is not None:
            preview.restore()
        if type(self.tool).__name__ == 'TexturePositionTool':
            self.tool._leave(self)
        self.cancel()
        self.tool = tool
        self.mode = TOOL_DISPATCH.get(type(tool).__name__, 'select' if tool is None else 'inert')
        if self.mode == 'move':
            # Share MoveTool's copy toggle, numeric values and array window.
            self.mode = 'mesh'
        if self.mode == 'tape':
            self.tool.on_cancel(self)
        if hasattr(tool, '_viewport'):
            tool._viewport = self
        self._notified_revision = getattr(getattr(source, 'history', None), 'revision', 0)
        if hasattr(self.view, 'setCursor'):
            self._apply_tool_cursor()
        if self.mode == 'inert':
            source.flash_status('not yet available on the Metal renderer')
        return self.mode

    def context(self, event):
        view = self.view
        point = (view.last_snap.point if getattr(view, 'last_snap', None) is not None
                 else view._world_under_cursor(event.position().x(), event.position().y()))
        if point is None:
            return None
        if type(self.tool).__name__ == 'FilletTool':
            self._hover_edge = self.pick_visible_edge(event.position().x(), event.position().y())
        if self.tool is not None:
            self.tool.snap_kind = getattr(view.last_snap, "kind", None)
        return ToolContext(self, point, event.position(), event.modifiers(), view.last_snap)

    def click(self, event):
        mode = self.sync()
        ctx = self.context(event)
        if ctx is None:
            return
        if mode == 'mesh':
            if (type(self.tool).__name__ == 'MoveTool'
                    and self.tool.start_point is None
                    and ctx.modifiers & Qt.ControlModifier and not self.tool._copy):
                self.tool._toggle_copy(self, say=False)
            self.tool.on_hover(ctx)
            self.tool.on_click(ctx)
            self.start_point = getattr(self.tool, 'start_point', None)
            self.update()
            self.view.overlay_primitives = []
            self.mesh_feedback()
        elif mode == 'tape':
            self.tool.on_click(ctx)
            self.start_point = getattr(self.tool, 'start_point', None)
            self.measurements()
        self.view.update()

    def hover(self, event):
        mode = self.sync()
        ctx = self.context(event)
        if ctx is None:
            return
        self.hover_point = ctx.world
        if mode == 'mesh':
            self.tool.on_hover(ctx)
            self.start_point = getattr(self.tool, 'start_point', None)
            self.mesh_feedback()
            return
        if mode == 'tape':
            self.tool.on_hover(ctx)
            self.measurements()
            lines = self.tool.rubber_band_lines()
            label = self.tool.value_label()
        else:
            return
        for a, b in lines:
            pa, pb = self.view._world_to_pixel(a), self.view._world_to_pixel(b)
            if pa is not None and pb is not None:
                self.view.overlay_primitives.append(Primitive('polyline', (pa, pb)))
        if label is not None:
            text, point = label
            pixel = self.view._world_to_pixel(point)
            if pixel is not None:
                self.view.overlay_primitives.append(Primitive('text', (pixel,), text=text))

    def key(self, event):
        if self.mode == 'mesh':
            from views.viewport import Viewport
            self._value_buffer = self.value_buffer
            if Viewport._handle_value_key(self, event):
                self.value_buffer = self._value_buffer
                self.start_point = getattr(self.tool, 'start_point', None)
                self.view.overlay_primitives = []
                self.update()
                self.mesh_feedback()
                return True
            return self.tool.on_key(self, event.key(), event.modifiers())
        return False

    def _current_token_tail(self):
        from views.viewport import Viewport
        return Viewport._current_token_tail(self)

    def _array_pending(self):
        return getattr(self.tool, 'array_pending', lambda vp: False)(self)

    def _release_axis_lock_after_operation(self, committed=False):
        release = getattr(self.view.source_viewport, '_release_axis_lock_after_operation', None)
        if release is not None:
            release(committed=committed)

    def _set_value_buffer(self, value):
        self._value_buffer = self.value_buffer = value
        self.measurementChanged.emit(value)

    def _parse_value_buffer(self, *args, **kwargs):
        from views.viewport import Viewport
        return Viewport._parse_value_buffer(*args, **kwargs)

    def write_rows(self, rows):
        if self.view.renderer is not None:
            self.view.renderer.update_instances(self.ids.tolist(), rows.view(np.uint8).reshape(-1))
        billboards = getattr(self.view, '_billboards', None)
        if billboards is not None:
            billboards.restore()
        self.view.packed.instances[self.ids] = rows
        from views.wgpu_parity import hidden_geometry
        hidden_geometry(self.view)
        if billboards is not None and len(billboards.ids):
            from views.wgpu_billboards import Billboards
            self.view._billboards = Billboards(self.view.packed)
            self.view._billboards.update(self.view.camera, self.view.renderer, self.view.inference_index)

    def restore(self):
        if self.original is not None:
            self.write_rows(self.original)

    def cancel(self):
        renderer = getattr(self.view, "renderer", None)
        if renderer is not None and hasattr(renderer, "set_preview_mesh"):
            empty = np.empty(0, np.uint8)
            renderer.set_preview_mesh(empty, empty)
        self.restore()
        if self.mode == 'mesh' and self.tool is not None:
            self.tool.on_cancel(self)
            self._mesh_hover = None
            self.update()
        if isinstance(self.tool, TapeMeasureTool):
            self.tool.on_cancel(self)
        self.original = None
        self.start_point = None
        if self.mode == "move" and self.tool is not None:
            self.tool.start_point = None
        self.value_buffer = ""
        self.view.overlay_primitives = []

    def measurements(self):
        source = self.view.source_viewport
        measured = getattr(self.tool, '_measured', None)
        if self.mode == 'tape' and self.start_point is None and measured is not None:
            from core.units import fmt_len_fine
            source.measurementChanged.emit(fmt_len_fine(measured))
        else:
            source.measurementChanged.emit(source._measurement_text())

    def flash_status(self, *args):
        self.view.source_viewport.flash_status(*args)

    def mesh_feedback(self):
        if type(self.tool).__name__ == 'TexturePositionTool':
            self.measurements()
            return
        super().mesh_feedback()

    def update(self):
        if self.mode == 'mesh':
            preview = getattr(self.view, '_texture_preview', None)
            if preview is not None:
                if not getattr(self.tool, 'active', False):
                    preview.restore()
            self.view.set_scene(self.scene)
            if type(self.tool).__name__ == 'TexturePositionTool':
                if preview is None:
                    from tools.texture_position_metal import TexturePreview
                    preview = self.view._texture_preview = TexturePreview(self.view)
                preview.update(self.tool)
            revision = self.history.revision
            if revision != getattr(self, '_notified_revision', revision):
                notify = getattr(self.view.source_viewport, 'notify_scene_changed', None)
                if notify is not None:
                    notify()
            self._notified_revision = revision
        self.view.update()

    def pick_edge_any(self, x, y):
        from views.wgpu_inference import reference_edge
        if getattr(self.view, 'inference_index', None) is None:
            return None
        return reference_edge(self.view.inference_index, self.view, x, y,
                              radius_px=self.pick_threshold_px)

    def pick_guide(self, x, y):
        # These shared projection-only pickers never read GL caches.
        from views.viewport import Viewport
        return Viewport.pick_guide(self, x, y) if self.scene is not None else None

    def pick_axis(self, x, y):
        from views.viewport import Viewport
        return Viewport.pick_axis(self, x, y) if self.scene is not None else None

    def width(self):
        return self.view.width()

    def height(self):
        return self.view.height()

    def _apply_tool_cursor(self):
        source = self.view.source_viewport
        # A nav mode (Orbit, Pan, Zoom) has no active tool: asking for the
        # tool cursor then unset the hand the mode had just put on.
        if getattr(source, 'nav_mode', None):
            apply = getattr(source, '_apply_nav_cursor', None)
        else:
            apply = getattr(source, '_apply_tool_cursor', None)
        if apply is not None:
            apply()
            if hasattr(self.view, 'setCursor'):
                self.view.setCursor(source.cursor())

    def edit_group_box_contains_pixel(self, x, y):
        return self.view.edit_group_box_contains_pixel(x, y)

    def __getattr__(self, name):
        return getattr(self.view.source_viewport, name)
