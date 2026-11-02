from PySide6.QtGui import QMatrix4x4, QVector3D as V
import pytest
from core.group import Group, copy_group, iter_placements
from core.mesh import Mesh
from core.scene import Scene
from core.history import History
from core.component_explode import ExplodeInContextCommand


def square():
    mesh = Mesh()
    mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return Group(mesh)


def points(group):
    return sorted(tuple(round(c, 4) for c in (p.x(), p.y(), p.z()))
                  for g, matrix in iter_placements(group)
                  for f in g.mesh.faces for v in f.vertices
                  for p in [matrix.map(v) if matrix is not None else v])


def model(copies=True, geometry=False):
    scene = Scene()
    target = square() if geometry else Group()
    child = square()
    target.adopt([child])
    target.xform.translate(2, 3, 0)
    parent = Group()
    parent.adopt([target])
    parent.xform.translate(10, 7, 0)
    parent.xform.rotate(30, V(0, 0, 1))
    peer = copy_group(parent, V(20, 0, 0)) if copies else None
    scene.groups = [parent] + ([peer] if peer else [])
    scene.begin_group_edit(parent)
    scene.selection = {target}
    return scene, parent, peer, target, child


@pytest.mark.parametrize('copies', [False, True])
def test_explode_component_structure_preserves_placement_and_undo(copies):
    """Left the way the app leaves, through the viewport: with copies, the
    assembly's matrix comes back up out of its parts on leaving, and the
    explode undoes inside the step that does it."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    scene, parent, peer, target, child = model(copies)
    scene.end_group_edit()
    before = [points(g) for g in scene.groups]
    win = MainWindow()
    vp = win.viewport
    vp.scene.groups[:] = scene.groups
    vp.scene.version += 1
    scene, hist = vp.scene, vp.history
    try:
        vp.begin_group_edit(parent)
        scene.selection = {target}
        hist.execute(ExplodeInContextCommand(parent, [target]))
        assert hist.last_error is None and hist.last_rejected is None
        assert parent.children == [child]
        assert scene.selection == {child}
        assert [points(g) for g in scene.groups] == before
        if peer:
            assert len(peer.children) == 1 and not peer.children[0].children
        vp.end_group_edit()
        assert hist.undo()
        assert parent.children == [target]
        assert [points(g) for g in scene.groups] == before
        assert hist.redo()
        assert parent.children == [child]
        assert [points(g) for g in scene.groups] == before
    finally:
        win._saved_version = scene.version
        win.close()


def test_geometry_can_explode_inside_a_single_component():
    scene, parent, _, target, child = model(False, True)
    before = points(parent)
    hist = History(scene)
    hist.execute(ExplodeInContextCommand(parent, [target]))
    assert hist.last_error is None and hist.last_rejected is None
    assert len(parent.mesh.faces) == 1
    assert points(parent) == before
    hist.undo()
    assert not parent.mesh.faces
    assert parent.children == [target]
    hist.redo()
    assert points(parent) == before


def test_shared_geometry_refusal_is_atomic():
    scene, parent, peer, target, child = model(True, True)
    before = [points(g) for g in scene.groups]
    hist = History(scene)
    hist.execute(ExplodeInContextCommand(parent, [target]))
    assert hist.last_rejected
    assert not hist.undo_stack
    assert parent.children == [target]
    assert scene.selection == {target}
    assert [points(g) for g in scene.groups] == before


def test_window_explode_does_not_refuse_component_context():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene, parent, _, target, child = model(False)
        win.viewport.set_document(scene, History(scene))
        win._on_explode_group()
        assert parent.children == [child]
        assert len(win.viewport.history.undo_stack) == 1
        win.viewport.history.undo()
        panel = win.project_browser.outliner
        assert panel.make_refusal([target])
        assert not panel.make_refusal([target], 'explode')
        panel.make_from_rows([target], 'explode')
        assert parent.children == [child]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_nested_plain_group_inside_repeated_component_updates_both():
    scene, parent, peer, target, child = model(True)
    # The selected container sits one level further inside a plain group.
    target.component = False
    peer.children[0].component = False
    inner = Group()
    inner.adopt([square()])
    target.children = [inner]
    peer.children[0].children = [copy_group(inner)]
    scene.begin_group_edit(target)
    before = [points(g) for g in scene.groups]
    hist = History(scene)
    hist.execute(ExplodeInContextCommand(target, [inner]))
    assert hist.last_error is None and hist.last_rejected is None
    assert not target.children[0].children
    assert not peer.children[0].children[0].children
    assert [points(g) for g in scene.groups] == before
    hist.undo()
    assert target.children == [inner]
    assert [points(g) for g in scene.groups] == before
