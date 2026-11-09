"""Maxence, 2026-11-10: viewport, Outliner and Entity Info file through one history."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMimeData, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from core import bim_registry, facets, structure
from core.agent_facets import set_display
from core.group import Group
from core.history import History
from core.layers import Layer
from tests.test_structure import model
from views.composer import SCENE_MIME
from views.structure_panel import BootstrapDialog, RecipeDialog, StructureDock
from views.tray import EntityInfoPanel


@pytest.fixture
def panel():
    scene, registry, filed, loose = model()
    registry['structure']['active'] = 'sections'
    structure.file(scene, [filed.uid], 'sections').do(scene)
    window = QMainWindow()
    vp = window.viewport = SimpleNamespace(scene=scene, history=History(scene), update=lambda: None)
    dock = StructureDock(window)
    vp.refresh_after_edit = dock.on_scene_changed
    window.addDockWidget(Qt.RightDockWidgetArea, dock)
    window.resize(600, 600)
    window.show()
    QApplication.processEvents()
    dock.refresh()
    yield dock, filed, loose
    window.close()
    window.deleteLater()


def test_tree_click_isolate_restore_and_colour(panel):
    dock, filed, loose = panel
    ride = dock.items['ride']
    assert ride.text(1) == '1' and ride.text(2) == '1'
    assert dock.items['sections'].font(0).bold()
    dock.tree.expandAll()
    row = dock.tree.visualItemRect(ride).center()
    QTest.mouseClick(dock.tree.viewport(), Qt.LeftButton, pos=row)
    assert dock.vp.scene.selection == {filed}
    set_display(dock.vp, color_by='structure')
    assert dock.vp.view_tint == {filed.uid: facets.palette('ride')}
    QTest.mouseDClick(dock.tree.viewport(), Qt.LeftButton, pos=row)
    assert dock.vp.scene._navigator_allowed == {filed.uid}
    assert not dock.vp.scene.entity_selectable(loose)
    dock.show_all()
    assert dock.vp.scene._navigator_allowed is None
    assert dock.vp.view_tint == {filed.uid: facets.palette('ride')}


def test_drop_names_and_undo(panel):
    dock, _, loose = panel
    data = QMimeData()
    data.setData(SCENE_MIME, loose.name.encode())
    assert dock.file_drop(data, 'sections')
    assert structure.node_of(loose) == 'sections'
    assert loose.layer == 'Track Sections' and loose.ifc['class'] == 'IfcMember'
    assert len(dock.vp.history.undo_stack) == 1
    dock.vp.history.undo()
    assert loose.layer is None and loose.ifc is None and structure.node_of(loose) is None


def test_refusal_shows_linked_uid(panel, monkeypatch):
    dock, _, loose = panel
    loose.ext = {'link': {'path': 'linked.igz'}}
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _, title, error: errors.append(error))
    dock.vp.scene.select([loose])
    dock.tree.setCurrentItem(dock.items['sections'])
    dock.file_button.click()
    assert 'Linked' in errors[0] and loose.uid in errors[0]
    assert not dock.vp.history.undo_stack


def test_unsorted_pages_select_and_file(panel):
    dock, _, loose = panel
    dock.vp.scene.groups.extend(Group(name=str(i)) for i in range(201))
    dock.vp.scene.version += 1
    dock.refresh()
    review = dock.review
    assert dock.tree.topLevelItem(dock.tree.topLevelItemCount() - 1) is review
    assert review.text(1) == '202' and review.childCount() == 0
    review.setExpanded(True)
    assert review.childCount() == 201
    row = review.child(0)
    assert row.text(0) == loose.name
    row.setSelected(True)
    dock.clicked(row, 0)
    assert dock.vp.scene.selection == {loose}
    dock.clicked(dock.more, 0)
    assert review.childCount() == 202 and dock.more is None
    assert dock.file_drop(dock.tree.mimeData([row]), 'ref')
    assert structure.node_of(loose) == 'ref'


def test_recipe_validation_and_atomic_resync(panel):
    dock, filed, _ = panel
    dialog = RecipeDialog(dock, dock.vp, 'sections')
    dialog.cls.addItem('BadClass')
    dialog.cls.setCurrentText('BadClass')
    dialog.submit()
    assert 'unknown class' in dialog.error.text()
    assert dock.vp.history.undo_stack == [] and filed.ifc['class'] == 'IfcMember'
    dialog.cls.setCurrentText('IfcColumn')
    dialog.status.setCurrentText('EXISTING')
    dialog.submit()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert filed.ifc['class'] == 'IfcColumn'
    assert filed.ifc['psets']['Pset_ColumnCommon']['Status']['value'] == 'EXISTING'
    assert len(dock.vp.history.undo_stack) == 1
    dock.vp.history.undo()
    reg = bim_registry.get(dock.vp.scene)
    assert structure.resolve(reg, 'sections')['class'] == filed.ifc['class'] == 'IfcMember'


def test_bootstrap_proposal_is_undoable(panel):
    dock, _, loose = panel
    scene = dock.vp.scene
    registry = bim_registry.get(scene)
    scene.layers.append(Layer('Survey'))
    loose.layer = 'Survey'
    dialog = BootstrapDialog(dock, dock.vp)
    assert not structure.node_of(loose)
    dialog.submit()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert structure.node_of(loose) == 'layer:' + scene.layer('Survey').uid
    assert len(dock.vp.history.undo_stack) == 1
    dock.vp.history.undo()
    assert bim_registry.get(scene) == registry and not structure.node_of(loose)


def test_entity_info_refiles_and_intercepts_tag(panel, monkeypatch):
    dock, filed, _ = panel
    scene = dock.vp.scene
    scene.select([filed])
    info = EntityInfoPanel(dock.window_owner)
    info.refresh()
    assert info._structure_path.text() == 'Ride › Track › Sections'
    monkeypatch.setattr('views.structure_panel.pick_node', lambda *_: 'ref')
    info._refile_button.click()
    assert info._structure_path.text() == 'Ride › Reference'
    monkeypatch.setattr('views.structure_panel.pick_node', lambda *_: None)
    info._layer_box.setCurrentIndex(info._layer_box.findData('Track Sections'))
    assert filed.layer == 'Reference' and info._layer_box.currentData() == 'Reference'
    assert len(dock.vp.history.undo_stack) == 1


def test_hidden_changes_coalesce_in_one_membership_pass(panel, monkeypatch):
    dock, _, _ = panel
    calls = []
    original = structure._memberships
    def counted(*args):
        calls.append(True)
        yield from original(*args)
    monkeypatch.setattr(structure, '_memberships', counted)
    dock.hide()
    for _ in range(3):
        dock.vp.scene.version += 1
        dock.on_scene_changed()
        dock.refresh()
    assert not calls and not dock.timer.isActive()
    dock.show()
    for _ in range(60):                 # a loaded machine delays the deferred slice
        QTest.qWait(50)
        if calls:
            break
    assert len(calls) == 1
    dock.vp.scene.bump_view()
    dock.refresh()
    assert len(calls) == 1


def test_outliner_group_drag_creates_visible_layer():
    from views.main_window import MainWindow
    from views.structure_panel import PLACEMENT_MIME
    window = MainWindow()
    try:
        vp = window.viewport
        scene = vp.scene
        group = Group(name='Beam')
        scene.groups.append(group)
        scene.plugin_data['bim_registry'] = {'structure': {'nodes': {
            'beams': {'name': 'Beams', 'order': 0, 'parent': None}}}}
        browser = window.project_browser.outliner
        browser.refresh()
        data = browser.tree.mimeData([browser._items[id(group)]])
        assert bytes(data.data(SCENE_MIME)).decode() == 'Beam'
        assert bytes(data.data(PLACEMENT_MIME)).decode() == group.uid
        assert window.structure_dock.file_drop(data, 'beams')
        QApplication.processEvents()
        assert ('layer', 'Beams', 0) in window.layers_dock.panel.display_outline()
    finally:
        window._saved_version = window.viewport.scene.version
        window.close()


def test_delete_occupied_leaf_refiles_in_one_step(panel, monkeypatch):
    dock, filed, _ = panel
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.Yes)
    dock.delete('sections')
    assert structure.node_of(filed) == 'track' and filed.layer == 'Track'
    assert 'sections' not in bim_registry.get(dock.vp.scene)['structure']['nodes']
    dock.vp.history.undo()
    assert structure.node_of(filed) == 'sections' and filed.layer == 'Track Sections'


def test_mounted_rows_and_exact_nested_members(panel):
    from views.viewport import Viewport
    dock, filed, loose = panel
    leaf = Group(name='Local')
    loose.children = [leaf]
    leaf.ext = {'structure': {'node': 'sections'}}
    source = 'ref/Supplier.igz'
    link = Group(name='Supplier')
    link.ext = {'link': {'path': source}}
    scene = dock.vp.scene
    scene.groups.append(link)
    registry = scene.plugin_data['bim_registry']
    registry['structure']['nodes']['mount'] = dict(name='Supplier', parent=None, order=1,
                                                 source=source, mount=True)
    scene.version += 1
    dock.refresh()
    assert dock.items['mount'].font(0).italic() and 'Supplier' in dock.items['mount'].text(0)
    dock.clicked(dock.items['sections'], 0)
    assert scene.selection == {filed, leaf}
    view = Viewport()
    try:
        view.scene = scene
        assert {g.uid for g in view._selected_group_placements()} == {filed.uid, leaf.uid}
    finally:
        view.close()
    dock.display('sections')
    assert scene._navigator_allowed == {filed.uid, leaf.uid}
