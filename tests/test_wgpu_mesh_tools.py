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
    native.view.last_snap = SimpleNamespace(point=QVector3D(*point), kind='endpoint', context=None)
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
                          SimpleNamespace(kind='endpoint', context=None))
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

from tools.eraser import EraserTool


@pytest.mark.parametrize('inside', [False, True])
def test_erase_stroke_commits_on_release(inside):
    scene, history, native, updates = harness(EraserTool(), inside)
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    native.pick_visible_edge = lambda *a: edge
    native.update()
    click(native, (0, 0, 0))
    assert not history.undo_stack
    native.tool.on_release(native)
    assert len(history.undo_stack) == 1
    assert not scene.mesh.edges
    assert len(updates.changed) == 1
    history.undo()
    native.update()
    assert edge in scene.mesh.edges
    assert len(updates.changed) == 1
    click(native, (0, 0, 0))
    native.cancel()
    native.tool.on_release(native)
    assert edge in scene.mesh.edges
    assert not native.view.overlay_primitives

from tools.move import MoveTool


@pytest.mark.parametrize('inside', [False, True])
@pytest.mark.parametrize('target', ['face', 'edge', 'vertex'])
def test_move_loose_preview_cancel_commit(inside, target):
    scene, history, native, updates = harness(MoveTool(), inside)
    face = scene.mesh.add_face([QVector3D(), QVector3D(2, 0, 0), QVector3D(0, 2, 0)])
    if target != 'vertex':
        scene.select([face if target == 'face' else scene.mesh.edges[0]])
    else:
        native.pick_group = lambda *a: None
        native.pick_edge = lambda *a: None
        native.pick_face = lambda *a: None
    native.update()
    before = geometry(scene.mesh)
    click(native, (0, 0, 0))
    native.view.last_snap = SimpleNamespace(point=QVector3D(0, 0, 1), kind='endpoint', context=None)
    native.hover(event())
    assert geometry(scene.mesh) != before
    native.cancel()
    assert geometry(scene.mesh) == before
    assert not native.view.overlay_primitives
    click(native, (0, 0, 0))
    click(native, (0, 0, 1))
    assert history.undo_stack
    assert len(updates.changed) <= 1
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before


def test_rectangle_vcb_dimensions_and_units():
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    scene, history, native, _ = harness(RectangleTool())
    click(native, (0, 0, 0))
    native.view.last_snap = SimpleNamespace(point=QVector3D(1, 1, 0), kind='endpoint', context=None)
    native.hover(event())
    for char in '200cm;300cm':
        assert native.key(QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, char))
    assert native.key(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert len(scene.mesh.faces) == 1
    points = [v.position for v in scene.mesh.vertices]
    assert max(p.x() for p in points) == pytest.approx(2.)
    assert max(p.y() for p in points) == pytest.approx(3.)
    assert not native.value_buffer
    assert history.undo_stack
