"""Shared menu commands against a Metal document, with real Qt widgets."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
from tests.test_wgpu_mesh_tools import app

def test_shared_menus_and_dock_selection(monkeypatch):
    monkeypatch.setenv('INGETRAZO_WGPU', '1')
    monkeypatch.setenv('INGETRAZO_AI_PORT', '0')
    from views.main_window import MainWindow, _prompts
    from views.scale_dialog import ScaleDialog
    monkeypatch.setattr(_prompts, 'get_text', lambda *a, **k: ('R3c component', True))
    import os
    if os.environ.get('INGETRAZO_R3_GUI') != '1':
        # This device-free menu test exercises routing, not adapter discovery.
        from core import renderer_settings
        monkeypatch.setattr(renderer_settings, 'capability',
                            lambda: renderer_settings.Capability(True))
    win = MainWindow()
    if os.environ.get('INGETRAZO_R3_GUI') == '1':
        win.show()
        QApplication.processEvents()
    vp = win.viewport
    scene = vp.scene
    scene.groups.clear()
    display = win._doc.stand_in
    try:
        face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                                    QVector3D(0, 2, 0)])
        scene.select([face])
        win._on_make_group()
        group = scene.groups[0]
        assert group in scene.selection
        display.set_scene(scene)
        win._on_make_component()
        assert group.is_component()
        vp.begin_group_edit(group)
        assert scene.edit_group is group
        vp.end_one_group_edit()
        assert scene.edit_group is None
        scene.select([group])
        win._on_hide()
        assert group.hidden
        win._on_unhide_all()
        assert not group.hidden
        win._lock_groups([group])
        assert group.locked
        win._unlock_group(group)
        assert not group.locked
        scene.select([group])
        browser = win.project_browser.outliner
        browser.refresh()
        assert browser._items[id(group)].isSelected()
        scene.clear_selection()
        browser._items[id(group)].setSelected(False)
        browser._items[id(group)].setSelected(True)
        assert group in scene.selection
        dock = win.structure_dock
        monkeypatch.setattr(dock, 'isVisible', lambda: True)
        dock.visibility(True)
        dock.refresh()
        dock.review.setExpanded(True)
        row = dock.review.child(0)
        scene.clear_selection()
        row.setSelected(True)
        dock.clicked(row, 0)
        assert group in scene.selection
        dialog = ScaleDialog(win, group)
        dialog.fields[0].setText('2')
        dialog._apply()
        assert vp.history.undo()
        assert vp.history.redo()
        dialog.reject()
        display.set_scene(scene)
        scene.select([group])
        win._on_explode_group()
        assert not scene.groups and scene.mesh.faces
        vp.history.undo()
        assert group in scene.groups
        display.set_scene(scene)
        if os.environ.get('INGETRAZO_R3_GUI') == '1':
            assert display.renderer is not None
            assert display.draw_frame() is not None
    finally:
        win._saved_version = scene.version
        win.close()
        QApplication.processEvents()
