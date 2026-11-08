"""Device-free regression checks for resident edits and shared tool semantics."""
from types import SimpleNamespace
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D, QMatrix4x4
from core.group import Group
from core.history import MoveGroupCommand, CompoundCommand
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.tape import TapeMeasureTool
from views.wgpu_scene import pack_scene
from views.wgpu_updates import InstanceUpdates
from views.wgpu_tools import TOOL_DISPATCH, move_command


def fixture_scene():
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(0, 3, 0)])
    groups = [Group(mesh), Group(mesh)]
    for g in groups:
        g.xform = QMatrix4x4()
    scene = Scene(groups=groups)
    return scene, InstanceUpdates(scene, pack_scene(scene))


class Renderer:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


def test_record_edits_submit_nothing():
    scene, updates = fixture_scene()
    scene.groups[0].ifc = {'class': 'IfcWall'}
    scene.version += 1
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    assert renderer.calls == []


def test_move_one_row_without_bake(monkeypatch):
    scene, updates = fixture_scene()
    monkeypatch.setattr('views.wgpu_updates.pack_scene', lambda *a: (_ for _ in ()).throw(AssertionError('bake')))
    scene.groups[1].xform.translate(4, 5, 6)
    ids, rows = updates.diff(scene)
    assert ids.tolist() == [1]
    renderer = Renderer()
    updates.apply(ids, rows, renderer)
    assert [name for name, _ in renderer.calls] == ['update_instances']
    np.testing.assert_array_equal(updates.packed.instances['world'][1, 3, :3], [4, 5, 6])


def test_add_shared_instance_and_remove_preserve_ids():
    scene, updates = fixture_scene()
    added = Group(scene.groups[0].mesh)
    scene.groups.append(added)
    ids, rows = updates.diff(scene)
    assert ids.tolist() == [2]
    updates.apply(ids, rows)
    scene.groups.pop(0)
    ids, rows = updates.diff(scene)
    updates.apply(ids, rows)
    assert updates.rows[added.uid] == 2
    assert updates.packed.instances['info'][0, 2] == 1


def test_shared_mutation_bakes_once(monkeypatch):
    scene, updates = fixture_scene()
    calls = []
    original = pack_scene
    monkeypatch.setattr('views.wgpu_updates.pack_scene', lambda scene: (calls.append(scene), original(scene))[1])
    mesh = scene.groups[0].mesh
    mesh.move_vertex(mesh.vertices[0], QVector3D(0, 0, 2))
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    assert len(calls) == 1
    assert len(calls[0].groups) == 1
    assert [name for name, _ in renderer.calls] == ['replace_prototype']


def test_move_command_matches_gl_and_undo():
    scene, _ = fixture_scene()
    delta = QVector3D(3, 4, 5)
    command = move_command(scene.groups[:1], delta)
    assert isinstance(command, MoveGroupCommand)
    before = scene.groups[0].xform.data()
    command.do(scene)
    assert scene.groups[0].xform.column(3).toVector3D() == delta
    command.undo(scene)
    assert scene.groups[0].xform.data() == before
    assert isinstance(move_command(scene.groups, delta), CompoundCommand)


def test_tape_matches_gl_measurement():
    from views.wgpu_tools import NativeTools
    tool = TapeMeasureTool()
    source = SimpleNamespace(active_tool=tool, flash_status=lambda *a: None,
                             measurementChanged=SimpleNamespace(emit=lambda *a: None),
                             _measurement_text=lambda: '')
    view = SimpleNamespace(source_viewport=source, overlay_primitives=[], update=lambda: None)
    native = NativeTools(view)
    native.sync()
    tool._mode = 'measure'
    event = SimpleNamespace(position=lambda: QPointF(), modifiers=lambda: Qt.NoModifier)
    for point in (QVector3D(1, 2, 3), QVector3D(4, 6, 3)):
        view.last_snap = SimpleNamespace(point=point, kind='endpoint')
        native.click(event)
    gl = TapeMeasureTool()
    gl._mode = 'measure'
    viewport = SimpleNamespace(pick_edge_any=lambda *a: None, update=lambda: None,
                               flash_status=lambda *a: None)
    for point in (QVector3D(1, 2, 3), QVector3D(4, 6, 3)):
        gl.on_click(ToolContext(viewport, point, QPointF(), Qt.NoModifier, None))
    assert tool._measured == gl._measured == 5.


def test_new_prototype_preserves_resident_ids():
    scene, updates = fixture_scene()
    mesh = Mesh()
    mesh.add_edge(QVector3D(), QVector3D(1, 1, 1))
    group = Group(mesh)
    scene.groups.append(group)
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    assert updates.rows[group.uid] == 2
    assert updates.packed.instances['info'][2, 0] == 1
    assert [name for name, _ in renderer.calls] == ['replace_prototype', 'update_instances']


def test_dispatch_is_explicit():
    assert TOOL_DISPATCH == {'SelectTool': 'select', 'TapeMeasureTool': 'tape', 'MoveTool': 'move'}
    assert TOOL_DISPATCH.get('RotateTool', 'inert') == 'inert'


def test_history_journal_limits_move_discovery(monkeypatch):
    from core.history import History, TagGroupsCommand
    scene, updates = fixture_scene()
    history = History(scene)
    updates.observe(history)
    history.execute(MoveGroupCommand(scene.groups[0], QVector3D(1, 0, 0)))
    ids, rows = updates.diff(scene)
    assert ids.tolist() == [0]
    updates.apply(ids, rows)
    monkeypatch.setattr('views.wgpu_updates.iter_placements', lambda *a: (_ for _ in ()).throw(AssertionError('scan')))
    history.execute(TagGroupsCommand(scene.groups, 'IfcWall'))
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    assert renderer.calls == []
