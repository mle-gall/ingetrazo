# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D, QMatrix4x4

from core.group import Group
from core.history import (AddEdgeCommand, Command, CommandRejected, FlipFacesCommand,
                          History, SetFaceColorCommand)
from core.mesh import DeferredMesh, Mesh
from core.scene import Scene


def edge():
    return AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0))


def test_listener_order_phases_unsubscribe_and_isolation(caplog):
    h = History(Scene())
    events = []
    def bad(*args):
        raise RuntimeError("listener error")
    h.add_listener(before=bad, after=bad)
    stop = h.add_listener(
        before=lambda c, p, ran: events.append(("before", c, p, ran)),
        after=lambda c, p, ran: events.append(("after", c, p, ran)))
    c = edge()
    h.execute(c)
    assert h.undo()
    assert h.redo()
    assert events == [(when, c, phase, when == "after")
                      for phase in ("execute", "undo", "redo")
                      for when in ("before", "after")]
    assert "listener error" in caplog.text
    stop()
    stop()
    h.execute(edge())
    assert len(events) == 6


@pytest.mark.parametrize("rejected", [True, False])
def test_failed_command_after_reports_false(tmp_path, rejected):
    class Fail(Command):
        def do(self, scene):
            raise CommandRejected("declined") if rejected else ValueError("failed")
        def undo(self, scene):
            pass
    h = History(Scene())
    h.error_log = str(tmp_path / "errors")
    events = []
    h.add_listener(after=lambda *args: events.append(args))
    c = Fail()
    h.execute(c)
    assert events == [(c, "execute", False)]
    assert h.revision == 0
    assert not h.undo_stack


def test_empty_history_does_not_notify():
    h = History(Scene())
    h.add_listener(before=lambda *a: pytest.fail("empty operation"))
    assert not h.undo()
    assert not h.redo()


def test_mesh_revision_geometry_attributes_winding_and_undo():
    scene = Scene()
    m = scene.mesh
    initial = m.revision
    face = m.add_face([QVector3D(), QVector3D(1, 0, 0), QVector3D(0, 1, 0)])
    assert m.revision > initial
    h = History(scene)
    for c in (SetFaceColorCommand([face], [1, 0, 0]), FlipFacesCommand([face])):
        before = m.revision
        h.execute(c)
        assert m.revision > before
        before = m.revision
        h.undo()
        assert m.revision > before
        before = m.revision
        h.redo()
        assert m.revision > before
    before = m.revision
    m._attrs_dirty = False
    m._chunk_dirty = False
    assert m.revision == before
    face.attrs["custom"] = 42
    m.mark_modified()
    assert m.revision > before


def test_deferred_revision_and_scene_reads_do_not_build():
    m = Mesh()
    assert DeferredMesh.defer(m, lambda m: pytest.fail("materialized"), 200000)
    scene = Scene(groups=[Group(m)])
    r = m.revision
    sr = scene.revision
    assert m.revision == r
    assert scene.revision == sr
    assert type(m) is DeferredMesh
    scene.groups[0].xform = QMatrix4x4()
    assert scene.revision > sr


def test_scene_tracks_tree_mesh_tags_and_undo():
    s = Scene()
    h = History(s)
    last = s.revision
    g = Group()
    for change in (lambda: s.groups.append(g),
                   lambda: g.mesh.add_edge(QVector3D(), QVector3D(1, 0, 0)),
                   lambda: setattr(g, "ext", {"intent": {"width": 2}}),
                   lambda: setattr(s.layers[0], "visible", False),
                   lambda: g.children.append(Group()),
                   lambda: s.groups.remove(g),
                   lambda: h.execute(edge()), h.undo, h.redo):
        change()
        now = s.revision
        assert now > last
        last = now
    s.bump_view()
    assert s.revision == last


def test_journal_extension_and_bridge():
    from views.extension_api import ExtensionApp
    from plugins.ai_bridge import _Bridge
    h = History(Scene())
    vp = SimpleNamespace(history=h, scene=h.scene)
    app = ExtensionApp(SimpleNamespace(viewport=vp), "test")
    events = []
    stop = app.add_command_listener(after=lambda *args: events.append(args))
    h.execute(edge())
    h.undo()
    result = _Bridge._tool_query_changes(SimpleNamespace(_viewport=vp), 0)
    assert result == {"revision": 2, "complete": True, "changes": [
        {"revision": 1, "phase": "execute", "command": "AddEdgeCommand"},
        {"revision": 2, "phase": "undo", "command": "AddEdgeCommand"}]}
    stop()
    assert len(events) == 2
    for _ in range(260):
        h.execute(edge())
    assert not h.changes_since(0)["complete"]
    assert h.changes_since(h.revision)["changes"] == []
    h.clear()
    assert h.revision == 262
    with pytest.raises(ValueError):
        h.changes_since(263)


def test_bulk_notifications_are_per_batch(monkeypatch):
    import numpy as np
    dirty = Mesh._chunk_dirty
    notifications = []
    def record(mesh, value):
        if value:
            notifications.append(mesh)
        dirty.fset(mesh, value)
    monkeypatch.setattr(Mesh, "_chunk_dirty", property(dirty.fget, record))
    counts = []
    for n in (10, 10000):
        mesh = Mesh()
        notifications.clear()
        pos = np.tile([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], (n, 1))
        mesh.add_faces_bulk(pos, np.full(n, 3), np.ones(n, dtype=int))
        counts.append(len(notifications))
    assert counts[0] == counts[1]
    assert 0 < counts[0] <= 3


def test_unsubscribe_during_dispatch_and_failed_undo():
    h = History(Scene())
    events = []
    stop = h.add_listener(before=lambda *a: stop(),
                          after=lambda *a: events.append(a))
    h.execute(edge())
    assert len(events) == 1
    h.undo()
    assert len(events) == 1

    class BrokenUndo(Command):
        def do(self, scene):
            scene.version += 1
        def undo(self, scene):
            raise ValueError("undo failed")
    c = BrokenUndo()
    h.execute(c)
    h.add_listener(after=lambda *a: events.append(a))
    with pytest.raises(ValueError, match="undo failed"):
        h.undo()
    assert events[-1] == (c, "undo", False)


def test_restamp_existing_edge_and_auto_tag_publish_mutations():
    from core.history import AutoTagDrawnFacesCommand
    scene = Scene()
    c = edge()
    c.do(scene)
    before = scene.mesh.revision
    AddEdgeCommand(c.a, c.b, soft=True).do(scene)
    assert scene.mesh.revision > before
    face = scene.mesh.add_face(
        [QVector3D(), QVector3D(1, 0, 0), QVector3D(0, 1, 0)])
    before = scene.mesh.revision
    AutoTagDrawnFacesCommand([SimpleNamespace(face=face)],
                            {"class": "IfcWall", "name": "Wall"}).do(scene)
    assert scene.mesh.revision > before
