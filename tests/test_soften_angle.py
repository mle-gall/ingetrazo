import math
from PySide6.QtGui import QVector3D as V
from core.mesh import Mesh
from core.group import Group, copy_group
from core.scene import Scene
from core.history import History
from core.soften import selected_edges, SoftenByAngleCommand
from tests.test_viewport_smooth_shading import _cylinder, _stub


def test_angle_updates_cylinder_sides_keeps_caps_and_undoes():
    scene = Scene()
    group = Group(_cylinder(Mesh(), soft=False))
    scene.groups = [group]
    scene.selection = {group}
    before = list(group.mesh.edges)
    hist = History(scene)
    hist.execute(SoftenByAngleCommand(selected_edges(scene), 40))
    assert hist.last_error is None
    assert sum(e.soft for e in before) == 12
    assert list(group.mesh.edges) == before
    hist.execute(SoftenByAngleCommand(selected_edges(scene), 10))
    assert not any(e.soft for e in before)
    hist.undo()
    assert sum(e.soft for e in before) == 12
    hist.undo()
    assert not any(e.soft for e in before)
    hist.redo()
    assert sum(e.soft for e in before) == 12


def test_face_selection_does_not_soften_its_outer_boundary():
    scene = Scene()
    _cylinder(scene.mesh, soft=False)
    scene.selection = set(scene.mesh.faces[:2])
    targets = selected_edges(scene)
    assert len(targets[scene.mesh]) == 1
    History(scene).execute(SoftenByAngleCommand(targets, 180))
    assert sum(e.soft for e in scene.mesh.edges) == 1


def test_nested_prototypes_are_processed_once_and_hidden_flags_survive():
    from PySide6.QtGui import QMatrix4x4
    scene = Scene()
    child = Group(_cylinder(Mesh(), soft=False))
    child.xform = QMatrix4x4()
    parent = Group()
    parent.adopt([child, copy_group(child)])
    scene.groups = [parent]
    scene.selection = {parent}
    edge = child.mesh.edges[0]
    edge.hidden = True
    targets = selected_edges(scene)
    assert len(targets[child.mesh]) == len(child.mesh.edges)
    History(scene).execute(SoftenByAngleCommand(targets, 40))
    assert edge.hidden
    assert parent.children[0].mesh is parent.children[1].mesh


def test_smoothing_invalidates_cached_chunk_and_undo_restores_it():
    scene = Scene()
    group = Group(_cylinder(Mesh(), soft=False))
    scene.groups = [group]
    scene.selection = {group}
    vp = _stub(scene)
    before = vp._group_chunk(group)['vcol']
    hist = History(scene)
    hist.execute(SoftenByAngleCommand(selected_edges(scene), 40))
    after = vp._group_chunk(group)['vcol']
    assert before != after
    hist.undo()
    assert vp._group_chunk(group)['vcol'] == before


def test_coplanar_and_unsoften_controls():
    scene = Scene()
    a = scene.mesh.add_face([V(0,0,0), V(1,0,0), V(1,1,0)])
    b = scene.mesh.add_face([V(0,0,0), V(1,1,0), V(0,1,0)])
    scene.selection = {a,b}
    hist = History(scene)
    targets = selected_edges(scene)
    hist.execute(SoftenByAngleCommand(targets, 1, coplanar=False))
    assert not any(e.soft for e in scene.mesh.edges)
    hist.execute(SoftenByAngleCommand(targets, 1))
    assert sum(e.soft for e in scene.mesh.edges) == 1
    hist.execute(SoftenByAngleCommand(targets, harden=True))
    assert not any(e.soft for e in scene.mesh.edges)
    hist.undo()
    assert sum(e.soft for e in scene.mesh.edges) == 1


def test_dialog_cancel_and_accept_use_one_undo_step(monkeypatch):
    from PySide6.QtWidgets import QDialog
    from views.main_window import MainWindow
    from views.soften_dialog import SoftenDialog
    win = MainWindow()
    try:
        scene = win.viewport.scene
        group = Group(_cylinder(Mesh(), soft=False))
        scene.groups = [group]
        scene.selection = {group}
        monkeypatch.setattr(SoftenDialog, 'exec', lambda self: QDialog.Rejected)
        win._on_soften_edges()
        assert not any(e.soft for e in group.mesh.edges)
        assert not win.viewport.history.undo_stack
        def accept(dialog):
            dialog.angle.setValue(40)
            return QDialog.Accepted
        monkeypatch.setattr(SoftenDialog, 'exec', accept)
        win._on_soften_edges()
        assert sum(e.soft for e in group.mesh.edges) == 12
        assert len(win.viewport.history.undo_stack) == 1
        win.viewport.history.undo()
        assert not any(e.soft for e in group.mesh.edges)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
