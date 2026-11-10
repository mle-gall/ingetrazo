"""Selecting thousands of groups syncs the Outliner in one selection, not one per row (2026-11-10)."""
import time

from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from PySide6.QtGui import QVector3D

_app = QApplication.instance() or QApplication([])


def _scene(n):
    scene = Scene()
    for i in range(n):
        mesh = Mesh()
        mesh.add_face([QVector3D(i, 0, 0), QVector3D(i + 1, 0, 0),
                       QVector3D(i + 1, 1, 0), QVector3D(i, 1, 0)])
        scene.groups.append(Group(mesh, name=f"g{i}"))
    return scene


def test_a_selection_of_thousands_syncs_in_one_go():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        for g in _scene(3000).groups:
            scene.groups.append(g)
        panel = win.project_browser.widget() if hasattr(win.project_browser, "widget") else win.project_browser
        panel = getattr(win, "project_browser")
        outl = getattr(panel, "_panel", None) or getattr(panel, "panel", None) or panel
        # reach the Outliner panel object that owns _sync_selection
        target = None
        for obj in (outl, getattr(outl, "widget", lambda: None)(), *outl.findChildren(object)):
            if hasattr(obj, "_sync_selection") and hasattr(obj, "_items"):
                target = obj
                break
        assert target is not None
        target.refresh() if hasattr(target, "refresh") else None
        _app.processEvents()
        scene.select(list(scene.groups))
        t = time.perf_counter()
        target._sync_selection(scene)
        took = time.perf_counter() - t
        selected = sum(1 for it in target._items.values() if it.isSelected())
        assert selected >= 2900, selected
        assert took < 3.0, took
        scene.select([])
        target._sync_selection(scene)
        assert not any(it.isSelected() for it in target._items.values())
    finally:
        win.close()
