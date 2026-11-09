"""Device-free regression checks for resident edits and shared tool semantics."""
from types import SimpleNamespace
import numpy as np
import pytest
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
    added.xform = QMatrix4x4()
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
    assert [name for name, _ in renderer.calls] == ['replace_prototype', 'update_prototype_materials']


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
    assert [name for name, _ in renderer.calls] == ['replace_prototype', 'update_prototype_materials', 'update_instances']


def test_dispatch_is_explicit():
    assert TOOL_DISPATCH == {'SelectTool': 'select', 'TapeMeasureTool': 'tape', 'MoveTool': 'move', 'LineTool': 'mesh', 'RectangleTool': 'mesh'}
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


def test_updated_bounds_match_fresh_pack():
    scene, updates = fixture_scene()
    scene.groups[0].xform.translate(20, -5, 8)
    updates.apply(*updates.diff(scene))
    np.testing.assert_allclose(updates.packed.world_bounds, pack_scene(scene).world_bounds)
    scene.groups.pop(0)
    updates.apply(*updates.diff(scene))
    np.testing.assert_allclose(updates.packed.world_bounds, pack_scene(scene).world_bounds)


def test_prototype_reassignment_preserves_row():
    scene, updates = fixture_scene()
    mesh = Mesh()
    mesh.add_edge(QVector3D(), QVector3D(2, 2, 2))
    scene.groups[0].mesh = mesh
    updates.apply(*updates.diff(scene))
    assert updates.rows[scene.groups[0].uid] == 0
    assert updates.packed.instances['info'][:, 0].tolist() == [1, 0]
    assert updates.packed.commands['start'].tolist() == [0, 1]


@pytest.mark.parametrize("completion", ["click", "escape", "enter"])
def test_native_move_preview_then_history_commit(completion):
    from core.history import History
    from tools.move import MoveTool
    from views.wgpu_tools import NativeTools
    scene, updates = fixture_scene()
    scene.select([scene.groups[0]])
    history = History(scene)
    source = SimpleNamespace(active_tool=MoveTool(), history=history,
                             flash_status=lambda *a: None, notify_scene_changed=lambda: None,
                             measurementChanged=SimpleNamespace(emit=lambda *a: None))
    view = SimpleNamespace(scene=scene, packed=updates.packed, renderer=Renderer(),
                           source_viewport=source, overlay_primitives=[],
                           uid_rows={uid: [row] for uid, row in updates.rows.items()},
                           _instance_updates=updates, update=lambda: None,
                           _world_to_pixel=lambda point: (point.x(), point.y()),
                           set_scene=lambda scene: updates.apply(*updates.diff(scene)))
    native = NativeTools(view)
    event = SimpleNamespace(position=lambda: QPointF(), modifiers=lambda: Qt.NoModifier)
    view.last_snap = SimpleNamespace(point=QVector3D(), kind='endpoint')
    native.click(event)
    view.last_snap = SimpleNamespace(point=QVector3D(2, 0, 0), kind='endpoint')
    native.hover(event)
    assert scene.groups[0].xform.column(3).x() == 0
    assert view.packed.instances['world'][0, 3, 0] == 2
    from views.wgpu_view import WgpuView
    view.tools = native
    if completion == 'escape':
        WgpuView.keyPressEvent(view, SimpleNamespace(key=lambda: Qt.Key_Escape))
        assert not history.undo_stack
        assert view.packed.instances['world'][0, 3, 0] == 0
        return
    if completion == 'enter':
        WgpuView.keyPressEvent(view, SimpleNamespace(key=lambda: Qt.Key_4, text=lambda: '4', modifiers=lambda: Qt.NoModifier))
        WgpuView.keyPressEvent(view, SimpleNamespace(key=lambda: Qt.Key_Return, text=lambda: '', modifiers=lambda: Qt.NoModifier))
    else:
        native.click(event)
    assert isinstance(history.undo_stack[-1], MoveGroupCommand)
    assert scene.groups[0].xform.column(3).x() == (4 if completion == 'enter' else 2)
    history.undo()
    assert scene.groups[0].xform.column(3).x() == 0


def test_inference_move_reuses_prototype_and_hits_updated_row():
    from views.wgpu_inference import prepare, surface
    scene, updates = fixture_scene()
    index = prepare(updates.packed)
    base, prototype = index.base, index.protos[0]
    scene.groups[0].xform.translate(10, 0, 0)
    ids, rows = updates.diff(scene)
    updates.apply(ids, rows)
    index.update(ids, updates.packed)
    assert index.base is base
    assert index.protos[0] is prototype
    hit = surface(index, 0, QVector3D(10.25, .25, 1), QVector3D(0, 0, -1))
    assert hit == QVector3D(10.25, .25, 0)
    assert surface(index, 1, QVector3D(.25, .25, 1), QVector3D(0, 0, -1)) == QVector3D(.25, .25, 0)


def test_inference_shared_mesh_change_invalidates_only_its_prototype():
    from views.wgpu_inference import prepare, surface
    scene, updates = fixture_scene()
    index = prepare(updates.packed)
    mesh = scene.groups[0].mesh
    for vertex in list(mesh.vertices):
        mesh.move_vertex(vertex, QVector3D(0, 0, 2))
    ids, rows = updates.diff(scene)
    updates.apply(ids, rows)
    index.update(ids, updates.packed, [code for _, _, code in updates.changed])
    assert surface(index, 1, QVector3D(.25, .25, 3), QVector3D(0, 0, -1)) == QVector3D(.25, .25, 2)


def test_uid_keeps_row_when_document_replaces_group_object():
    scene, updates = fixture_scene()
    replacement = Group(scene.groups[0].mesh)
    replacement.uid = scene.groups[0].uid
    replacement.xform = QMatrix4x4()
    scene.groups[0] = replacement
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    assert updates.packed.groups[0] is replacement
    assert renderer.calls == []


def test_history_insert_undo_redo_keeps_one_row(monkeypatch):
    from core.history import History, InsertGroupCommand
    from core.group import iter_placements
    scene, updates = fixture_scene()
    history = History(scene)
    updates.observe(history)
    added = Group(scene.groups[0].mesh)
    added.xform = QMatrix4x4()
    visited = []
    monkeypatch.setattr('views.wgpu_updates.iter_placements',
                        lambda group: (visited.append(group), iter_placements(group))[1])
    history.execute(InsertGroupCommand(added))
    ids, rows = updates.diff(scene)
    assert visited == [added]
    assert ids.tolist() == [2]
    updates.apply(ids, rows)
    history.undo()
    updates.apply(*updates.diff(scene))
    assert updates.packed.instances['info'][2, 2] == 1
    history.redo()
    ids, rows = updates.diff(scene)
    assert ids.tolist() == [2]
    updates.apply(ids, rows)
    assert updates.packed.instances['info'][2, 2] == 0


def test_tool_change_signal_reports_unsupported_tool_without_mouse_input():
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from views.wgpu_view import WgpuView
    app = QApplication.instance() or QApplication([])
    messages = []
    class Source(QObject):
        measurementChanged = Signal(str)
        active_tool = None

        def flash_status(self, message):
            messages.append(message)

    source = Source()
    view = WgpuView()
    view.source_viewport = source
    view._observe_tool_source()
    view.show()
    source.active_tool = SimpleNamespace()
    source.measurementChanged.emit('')
    app.processEvents()
    assert view.tools.mode == 'inert'
    assert messages == ['not yet available on the Metal renderer']
    view.close()


def test_prototype_bake_does_not_consume_document_group_names(monkeypatch):
    import itertools
    import core.group as groups
    monkeypatch.setattr(groups, '_counter', itertools.count(100))
    scene, updates = fixture_scene()
    before = next(groups._counter)
    mesh = scene.groups[0].mesh
    mesh.move_vertex(mesh.vertices[0], QVector3D(0, 0, 1))
    updates.apply(*updates.diff(scene))
    assert next(groups._counter) == before + 1


def test_replacement_preserves_full_material_rows_and_resident_texture_ids(tmp_path):
    from PySide6.QtGui import QImage, QColor
    meshes = []
    for name in ('red', 'blue'):
        image = QImage(2, 2, QImage.Format_RGBA8888)
        image.fill(QColor(name))
        path = tmp_path / (name + '.png')
        assert image.save(str(path))
        mesh = Mesh()
        mesh.add_face([QVector3D(), QVector3D(1, 0, 0), QVector3D(0, 1, 0)])
        mesh.faces[0].attrs['texture'] = {'path': str(path)}
        meshes.append(mesh)
    scene = Scene(groups=[Group(mesh) for mesh in meshes])
    updates = InstanceUpdates(scene, pack_scene(scene))
    meshes[1].move_vertex(meshes[1].vertices[0], QVector3D(0, 0, .1))
    renderer = Renderer()
    updates.apply(*updates.diff(scene), renderer)
    materials = next(args[1] for name, args in renderer.calls if name == 'update_prototype_materials')
    assert materials.nbytes == 3 * 32
    assert materials.view(np.uint32).reshape(-1, 8)[:, 5].tolist() == [2, 2, 2]
    assert not any(name == 'set_textures' for name, _ in renderer.calls)


def test_drag_preview_batches_rows_without_rendering_ids():
    from views.wgpu_tools import NativeTools
    from views.wgpu_scene import INSTANCE
    renderer = Renderer()
    packed = SimpleNamespace(instances=np.zeros(2000, dtype=INSTANCE))
    view = SimpleNamespace(renderer=renderer, packed=packed)
    native = NativeTools(view)
    native.ids = np.arange(0, 2000, 2, dtype=np.int64)
    rows = packed.instances[native.ids].copy()
    rows['world'][:, 3, 0] = 7
    native.write_rows(rows)
    assert [name for name, _ in renderer.calls] == ['update_instances']
    assert renderer.calls[0][1][0] == native.ids.tolist()
    assert len(renderer.calls[0][1][1]) == 1000 * 80
    assert np.all(packed.instances['world'][native.ids, 3, 0] == 7)
    assert np.all(packed.instances['world'][1::2, 3, 0] == 0)
