# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «In model» list draws the pictures of the rows on screen only: a
plant of 1 815 components drew every one at each refresh, a quarter of
opening it (#158). Scrolled to, a row gets its picture; the picture is
the one drawn before."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views import component_thumbs


def _component(i):
    m = Mesh()
    s = 1.0 + i * 0.01
    m.add_face([V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0)])
    g = Group(m, name=f"C{i:03d}")
    xf = QMatrix4x4()
    xf.translate(i * 2.0, 0.0, 0.0)
    g.xform = xf
    return g


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def test_only_rows_on_screen_are_drawn(monkeypatch):
    from views.main_window import MainWindow
    drawn = []
    real = component_thumbs._draw

    def spy(definition, size):
        drawn.append(definition.name)
        return real(definition, size)
    monkeypatch.setattr(component_thumbs, "_draw", spy)
    component_thumbs._cache.clear()
    win = MainWindow()
    try:
        win.show()
        scene = win.viewport.scene
        scene.groups.extend(_component(i) for i in range(120))
        panel = win.tray.components
        panel.refresh_in_model()
        _settle()
        lst = panel._in_model
        assert lst.count() == 120
        assert drawn, "the rows on screen get their picture"
        assert len(drawn) < 60, "rows off screen wait to be scrolled to"
        first = set(drawn)
        lst.scrollToItem(lst.item(119))
        _settle()
        last = lst.item(119).data(Qt.UserRole)[0].name
        assert last in drawn and last not in first
        assert lst.item(119).data(Qt.UserRole + 2)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_nested_lazy_thumbnail_matches_eager_without_materialization(monkeypatch, tmp_path):
    import pytest
    from core.scene import Scene
    from core.mesh import DeferredMesh
    from formats import igz
    from tests.test_deferred_mesh import _open
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(component_thumbs, "MAX_FACES", 5)
    proto = _component(0).mesh
    proto.faces[0].attrs["color"] = [0.8, 0.2, 0.4]
    children = []
    for i in range(13):
        g = Group(proto, name=str(i))
        g.xform = QMatrix4x4()
        g.xform.translate(i % 4, i // 4, i * 0.1)
        g.xform.rotate(i * 7, 0, 0, 1)
        children.append(g)
    root = Group(name="assembly")
    root.adopt(children)
    sc = Scene()
    sc.groups.append(root)
    path = tmp_path / "thumb.igz"
    igz.save_scene(sc, path)
    eager = _open(monkeypatch, path, False).groups[0]
    lazy = _open(monkeypatch, path, True).groups[0]
    assert type(lazy.children[0].mesh) is DeferredMesh
    expected = component_thumbs._draw(eager, 80).toImage()
    monkeypatch.setattr(DeferredMesh, "_materialize", lambda self: pytest.fail(
        "a thumbnail built editable mesh topology"))
    actual = component_thumbs.thumbnail(lazy, 80).toImage()
    assert actual == expected
    # Signature validation and a second picture must remain lazy too.
    assert component_thumbs.thumbnail(lazy, 80).toImage() == expected
