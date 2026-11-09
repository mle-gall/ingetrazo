"""Native routing invokes the document tools, including History and cancellation."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.history import History
from tools.line import LineTool
from tools.rectangle import RectangleTool
from tools.base import ToolContext
from views.wgpu_tools import NativeTools
from views.wgpu_scene import pack_scene
from views.wgpu_updates import InstanceUpdates

app = QApplication.instance() or QApplication([])


def harness(tool, inside=False):
    scene = Scene()
    if inside:
        group = Group(Mesh())
        scene.groups.append(group)
        scene.begin_group_edit(group)
    history = History(scene)
    source = SimpleNamespace(scene=scene, history=history, active_tool=tool,
        flash_status=lambda *a: None, measurementChanged=SimpleNamespace(emit=lambda *a: None),
        _measurement_text=lambda: '')
    updates = InstanceUpdates(scene, pack_scene(scene))
    updates.observe(history)
    def refresh(scene):
        updates.apply(*updates.diff(scene))
    view = SimpleNamespace(source_viewport=source, scene=scene, overlay_primitives=[],
        update=lambda: None, set_scene=refresh, _world_to_pixel=lambda p: (p.x(), p.y()))
    native = NativeTools(view)
    native.sync()
    return scene, history, native, updates


def event():
    return SimpleNamespace(position=lambda: QPointF(), modifiers=lambda: Qt.NoModifier)


def click(native, point):
    native.view.last_snap = SimpleNamespace(point=QVector3D(*point), kind='endpoint')
    native.click(event())


def geometry(mesh):
    return sorted(tuple(v.position.toTuple()) for v in mesh.vertices), len(mesh.edges), len(mesh.faces)


@pytest.mark.parametrize('tool_type', [LineTool, RectangleTool])
@pytest.mark.parametrize('inside', [False, True])
def test_draw_commands_match_direct_tool_and_restore(tool_type, inside):
    scene, history, native, updates = harness(tool_type(), inside)
    gl_scene, gl_history, direct, _ = harness(tool_type(), inside)
    before = geometry(scene.mesh)
    for p in [(0, 0, 0), (2, 3, 0)]:
        click(native, p)
        ctx = ToolContext(direct, QVector3D(*p), QPointF(), Qt.NoModifier,
                          SimpleNamespace(kind='endpoint'))
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
    assert type(history.undo_stack[-1]) is type(gl_history.undo_stack[-1])
    assert geometry(scene.mesh) == geometry(gl_scene.mesh)
    history.undo()
    delta = updates.diff(scene)
    assert len(updates.changed) == 1
    gl_history.undo()
    assert geometry(scene.mesh) == geometry(gl_scene.mesh)
    assert geometry(scene.mesh)[1:] == before[1:]
    updates.apply(*delta)
    history.redo()
    updates.diff(scene)
    assert len(updates.changed) == 1
    native.cancel()
    assert native.tool.start_point is None
    assert not native.view.overlay_primitives

from tools.pushpull import PushPullTool


@pytest.mark.parametrize('inside', [False, True])
def test_pushpull_numeric_commit_and_cancel(inside):
    scene, history, native, updates = harness(PushPullTool(), inside)
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                                QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    native.pick_face_any = lambda *a: (face, None)
    native._ray_hit_plane = lambda *a: QVector3D(1, 1, 0)
    native.update()
    before = geometry(scene.mesh)
    click(native, (1, 1, 0))
    assert native.tool.dragging
    assert native.tool.on_value(native, 1.)
    assert len(history.undo_stack) == 1
    assert len(scene.mesh.faces) > before[2]
    assert len(updates.changed) == 1
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert len(updates.changed) == 1
    native.cancel()
    assert not native.tool.dragging
    assert not native.view.overlay_primitives
