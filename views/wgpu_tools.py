"""Native tool dispatch shares measurement and History semantics with GL.

Live placement moves alter resident matrices only; the document is touched
once, by the same commands used by MoveTool, after the user commits.
"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from core.group import Group, iter_placements
from core.history import MoveGroupCommand, CompoundCommand
from tools.base import ToolContext
from tools.tape import TapeMeasureTool
from views.wgpu_overlay import Primitive

TOOL_DISPATCH = {'SelectTool': 'select', 'TapeMeasureTool': 'tape', 'MoveTool': 'move', 'LineTool': 'mesh', 'RectangleTool': 'mesh', 'PushPullTool': 'mesh', 'EraserTool': 'mesh', 'RotateTool': 'mesh', 'ScaleTool': 'mesh'}


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

    def sync(self):
        source = self.view.source_viewport
        tool = getattr(source, 'active_tool', None)
        if tool is self.tool:
            if self.mode in ('tape', 'move') and self.start_point is not None and getattr(tool, 'start_point', None) is None:
                self.cancel()
            return self.mode
        self.cancel()
        self.tool = tool
        self.mode = TOOL_DISPATCH.get(type(tool).__name__, 'select' if tool is None else 'inert')
        if self.mode == 'move':
            selection = self.view.scene.selection
            if not selection or not all(isinstance(g, Group) for g in selection):
                self.mode = 'mesh'
        if self.mode == 'tape':
            self.tool.on_cancel(self)
        if self.mode == 'inert':
            source.flash_status('not yet available on the Metal renderer')
        return self.mode

    def context(self, event):
        view = self.view
        point = (view.last_snap.point if getattr(view, 'last_snap', None) is not None
                 else view._world_under_cursor(event.position().x(), event.position().y()))
        if point is None:
            return None
        if self.tool is not None:
            self.tool.snap_kind = getattr(view.last_snap, "kind", None)
        return ToolContext(self, point, event.position(), event.modifiers(), view.last_snap)

    def click(self, event):
        mode = self.sync()
        ctx = self.context(event)
        if ctx is None:
            return
        if mode == 'mesh':
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
        elif mode == 'move':
            if self.start_point is None:
                self.groups = [g for g in self.view.scene.selection if isinstance(g, Group)]
                # A selected parent carries descendants; never move them twice.
                children = {id(child) for g in self.groups for child, _ in list(iter_placements(g))[1:]}
                self.groups = [g for g in self.groups if id(g) not in children]
                if not self.groups:
                    self.flash_status('Select whole placements to move')
                    return
                selected = {g.uid for root in self.groups for g, _ in iter_placements(root)}
                self.ids = np.asarray([row for uid in selected for row in self.view.uid_rows.get(uid, ())], np.int64)
                self.original = self.view.packed.instances[self.ids].copy()
                self.start_point = QVector3D(ctx.world)
                self.tool.start_point = QVector3D(ctx.world)
                self.preview_delta = (0., 0., 0.)
                self.hover(event)
            else:
                delta = ctx.world - self.start_point
                self.restore()
                if delta.lengthSquared() > 1e-18:
                    self.view.source_viewport.history.execute(move_command(self.groups, delta))
                    self.view.source_viewport.notify_scene_changed()
                    self.view.set_scene(self.view.scene)
                self.start_point = None
                self.tool.start_point = None
                self.original = None
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
        elif mode == 'move' and self.start_point is not None:
            delta = (ctx.world-self.start_point).toTuple()
            if delta != self.preview_delta:
                rows = self.original.copy()
                rows['world'][:, 3, :3] += np.asarray(delta, np.float32)
                self.write_rows(rows)
                self.preview_delta = delta
            lines = [(self.start_point, ctx.world)]
            from core.units import fmt_len
            label = (fmt_len((ctx.world-self.start_point).length()), (ctx.world+self.start_point)*.5)
            self.view.source_viewport.measurementChanged.emit(label[0])
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
        if self.mode != 'move' or self.start_point is None:
            return False
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            from views.viewport import Viewport
            value = Viewport._parse_value_buffer(self.value_buffer)
            if isinstance(value, (int, float)) and self.hover_point is not None:
                delta = self.hover_point - self.start_point
                if delta.lengthSquared() > 1e-18:
                    self.restore()
                    self.view.source_viewport.history.execute(move_command(self.groups, delta.normalized()*value))
                    self.original = None
                    self.start_point = None
                    self.tool.start_point = None
                    self.view.source_viewport.notify_scene_changed()
                    self.view.set_scene(self.view.scene)
            self.value_buffer = ''
            return True
        text = event.text()
        if text and not (event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)) and (text[0].isdigit() or text in '.-+,'):
            self.value_buffer += text
            self.view.source_viewport.measurementChanged.emit(self.value_buffer)
            return True
        if event.key() == Qt.Key_Backspace:
            self.value_buffer = self.value_buffer[:-1]
            return True
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
        self.view.packed.instances[self.ids] = rows

    def restore(self):
        if self.original is not None:
            self.write_rows(self.original)

    def cancel(self):
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

    def update(self):
        if self.mode == 'mesh':
            self.view.set_scene(self.scene)
            revision = self.history.revision
            if revision != getattr(self, '_notified_revision', revision):
                notify = getattr(self.view.source_viewport, 'notify_scene_changed', None)
                if notify is not None:
                    notify()
            self._notified_revision = revision
        self.view.update()

    # R2b measures points, not guide creation from GL edge picking.
    def pick_edge_any(self, x, y):
        return None

    def pick_guide(self, x, y):
        return None

    def pick_axis(self, x, y):
        return None

    def __getattr__(self, name):
        return getattr(self.view.source_viewport, name)
