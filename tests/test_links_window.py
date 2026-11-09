# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Linked documents in the real window: link one, its tags in the Tags
panel's folders, saving the source in another tab reloads the host, and
going into the linked copy offers to open its file."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import links  # noqa: E402
from formats import igz  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _settle(ms: int = 0) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _source(path, faces=1):
    from core.layers import Layer
    from core.scene import Scene
    s = Scene()
    s.layers.append(Layer("Wood"))
    for i in range(faces):
        f = s.mesh.add_face([V(i, 0, 0), V(i + 1, 0, 0), V(i + 1, 1, 0),
                             V(i, 1, 0)])
        f.attrs = {"layer": "Wood"}
    igz.save_scene(s, path)
    return path


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for d in w.documents():
        d.saved_content = d.viewport.scene.content_version
    w.close()


def _faces(g):
    from core.group import iter_placements
    return sum(len(p.mesh.faces) for p, _m in iter_placements(g))


def test_link_place_and_reload_when_the_source_changes(win, tmp_path):
    src = _source(tmp_path / "Site.igz", faces=1)
    win.link_igz_path(src, at=(0, 0, 0))
    scene = win.viewport.scene
    (g,) = links.linked_groups(scene)
    assert _faces(g) == 1
    assert scene.layer("Site / Wood") is not None
    assert str(src.resolve()) in win._link_watcher()._fs.files()
    # The source changes on disk (another tab's save, another app).
    _source(src, faces=3)
    win._link_watcher()._changed(str(src.resolve()))
    _settle(win._link_watcher().SETTLE_MS * 4)   # the OS event restarts it
    (g,) = links.linked_groups(scene)
    assert _faces(g) == 3


def test_going_into_a_linked_copy_offers_its_file(win, tmp_path, monkeypatch):
    src = _source(tmp_path / "Site.igz")
    win.link_igz_path(src, at=(0, 0, 0))
    (g,) = links.linked_groups(win.viewport.scene)
    asked = {}

    def fake_exec(box):
        asked["text"] = box.text()
        box._picked = box.buttons()[0]          # «Open Site.igz»
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda box: getattr(box, "_picked", None))
    win.viewport.begin_group_edit(g)
    assert "Site.igz" in asked["text"]
    assert win.viewport.scene.edit_group is None        # never entered
    assert any(d.same_file(src) for d in win.documents())


def test_save_as_placeholder_and_reopen(win, tmp_path):
    src = _source(tmp_path / "Site.igz", faces=2)
    win.link_igz_path(src, at=(0, 0, 0))
    host = tmp_path / "Host.igz"
    win._do_save(host)
    win.open_path(host)
    _settle()
    (g,) = links.linked_groups(win.viewport.scene)
    assert _faces(g) == 2


def test_links_tab_subset_and_agent_surface(win, tmp_path):
    from core.group import Group
    from core.scene import Scene
    from core.agent_tools import BUILTIN_TOOLS
    scene = Scene()
    scene.groups = [Group(name='A'), Group(name='B')]
    path = tmp_path / 'parts.igz'
    igz.save_scene(scene, path)
    win.link_igz_path(path, at=(0, 0, 0), select={'uids': [scene.groups[0].uid]})
    panel = win.project_browser.links_panel
    panel.refresh()
    assert panel.tree.topLevelItemCount() == 1
    item = panel.tree.topLevelItem(0)
    assert item.text(1) == 'resolved'
    assert item.text(2) == '1 UIDs'
    assert item.text(3) == '1'
    panel.tree.setCurrentItem(item)
    panel.pack()
    assert panel.tree.topLevelItem(0).text(1) == 'packed'
    assert {'query_links', 'link_document', 'reload_link', 'query_project', 'set_project'} <= {t['name'] for t in BUILTIN_TOOLS}
