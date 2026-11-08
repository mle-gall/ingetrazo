# SPDX-License-Identifier: GPL-3.0-or-later
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication
from core.group import Group
from core.mesh import Mesh
from core.layers import Layer
from plugins.ai_bridge import _Bridge
from views.extension_api import ExtensionApp
from tests.test_ai_bridge import _ask


@pytest.fixture
def model(monkeypatch):
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups.clear()
    mesh = Mesh()
    mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(0, 2, 0)])
    child = Group(mesh, name="Child")
    parent = Group(Mesh(), name="Parent")
    parent.children = [child]
    parent.xform = QMatrix4x4()
    parent.xform.translate(10, 0, 0)
    child.ifc = {"class": "IfcWall", "custom": {"a": 1}}
    scene.groups.append(parent)
    layer = Layer("Walls")
    scene.layers.append(layer)
    child.layer = layer.name
    bridge = _Bridge(win.viewport)
    yield win, bridge, parent, child, layer
    bridge.stop()
    win._saved_version = scene.version
    win.close()


def call(bridge, tool, **args):
    job = dict(req=dict(id=1, tool=tool, args=args), done=threading.Event())
    bridge._run_on_main(job)
    assert job["done"].is_set()
    assert job["reply"]["ok"], job["reply"]
    return job["reply"]["result"]


def test_registry_extension_socket_and_unload(model):
    win, bridge, *_ = model
    app = ExtensionApp(win, "demo")
    seen = []
    off = app.add_agent_tool("hello", lambda text: seen.append(threading.current_thread()) or text,
                             description="Echo", input_schema={"type": "object"})
    with pytest.raises(ValueError):
        app.add_agent_tool("hello", lambda: None, description="Duplicate")
    with pytest.raises(ValueError):
        app.add_agent_tool("undo", lambda: None, description="Duplicate")
    bridge.start()
    assert _ask(bridge, "hello", {"text": "hi"})["result"] == "hi"
    assert seen == [threading.main_thread()]
    assert "hello" in {s["name"] for s in call(bridge, "list_tools")["tools"]}
    off(); off()
    assert "hello" not in {s["name"] for s in call(bridge, "list_tools")["tools"]}
    app.add_agent_tool("bye", lambda: None, description="Bye")
    app.remove_agent_tools()
    assert "bye" not in bridge._extension_tools
    assert "unknown tool 'hello'" in _ask(bridge, "hello")["error"]


@pytest.mark.parametrize("failure", ["exception", "object", "nan"])
def test_mutation_rolls_back_on_error_or_non_json_result(model, failure):
    win, bridge, *_ = model
    app = ExtensionApp(win, "demo")
    def broken():
        win.viewport.scene.groups.append(Group(Mesh(), name="Temporary"))
        if failure == "exception":
            raise ValueError("broken")
        return object() if failure == "object" else float("nan")
    app.add_agent_tool("broken", broken, description="Broken", mutates=True)
    bridge.start()
    before = len(win.viewport.history.undo_stack)
    result = _ask(bridge, "broken")
    assert not result["ok"]
    assert [g.name for g in win.viewport.scene.groups] == ["Parent"]
    assert len(win.viewport.history.undo_stack) == before


def test_mutation_undo_redo(model):
    win, bridge, *_ = model
    def add():
        win.viewport.scene.groups.append(Group(Mesh(), name="Added"))
        return {"added": True}
    ExtensionApp(win, "demo").add_agent_tool("add", add, description="Add", mutates=True)
    before = len(win.viewport.history.undo_stack)
    assert call(bridge, "add") == {"added": True}
    assert len(win.viewport.history.undo_stack) == before + 1
    call(bridge, "undo")
    assert len(win.viewport.scene.groups) == 1
    call(bridge, "redo")
    assert len(win.viewport.scene.groups) == 2


def test_tree_entity_selection_and_layers(model):
    win, bridge, parent, child, layer = model
    tree = call(bridge, "query_tree", limit=1)
    assert tree["rows"][0]["uid"] == parent.uid
    assert tree["next_offset"] == 1
    entity = call(bridge, "query_entity", uid=child.uid)
    assert entity["path"] == ["Parent"]
    assert entity["bounds"] == {"min": [10, 0, 0], "max": [12, 2, 0]}
    assert entity["ifc"] == child.ifc
    assert entity["faces"] == 1 and entity["edges"] == 3
    assert entity["placement_matrix"][12] == 10
    assert call(bridge, "query_tree", root_uid=child.uid, depth=0)["rows"][0]["depth"] == 0
    twin = Group(child.mesh, name="Twin")
    win.viewport.scene.groups.append(twin)
    assert call(bridge, "query_entity", uid=twin.uid)["shared_definition_key"] == entity["shared_definition_key"]
    child.hidden = True
    assert child.uid not in [r["uid"] for r in call(bridge, "query_tree", include_hidden=False)["rows"]]
    child.hidden = False
    result = call(bridge, "select", pattern="Chi*")
    assert result["bounds"] == entity["bounds"] and result["groups"][0]["class"] == "IfcWall"
    assert len(call(bridge, "select", uids=[parent.uid], mode="add")["groups"]) == 2
    assert len(call(bridge, "select", uids=[parent.uid], mode="remove")["groups"]) == 1
    assert not call(bridge, "select", mode="clear")["groups"]
    rows = call(bridge, "query_layers")["layers"]
    assert next(r for r in rows if r["uid"] == layer.uid)["groups"] == 1
    call(bridge, "set_layer_visibility", uids_or_names=[layer.uid], visible=False)
    assert not layer.visible
    win.layers_dock.panel.previous_state()
    assert win.viewport.scene.layer("Walls").visible


def test_camera_zoom_and_screenshot(model, monkeypatch):
    win, bridge, parent, child, _ = model
    before = len(win.viewport.history.undo_stack)
    for preset in win.viewport.camera._STANDARD_VIEWS:
        assert call(bridge, "set_camera", preset=preset, ortho=True)["preset"] == preset
    camera = call(bridge, "set_camera", eye=[10, -10, 10], target=[10, 0, 0], up=[0, 0, 1], ortho=False)
    assert camera["target"] == pytest.approx([10, 0, 0])
    call(bridge, "zoom_to", uids=[child.uid])
    assert 10 <= call(bridge, "query_camera")["target"][0] <= 12
    from PySide6.QtGui import QImage
    monkeypatch.setattr(win.viewport, "render_image", lambda w, h: QImage(w, h, QImage.Format_RGB32))
    shot = call(bridge, "screenshot", uids=[child.uid], width=64, height=64)
    assert shot["camera"] == call(bridge, "query_camera")
    assert len(win.viewport.history.undo_stack) == before


def test_existing_nested_metadata_and_mesh_are_transactional(model):
    win, bridge, parent, child, layer = model
    original = child.mesh.capture_state()
    def edit(fail=False):
        child.name = "Edited"
        child.ifc["custom"]["a"] = 7
        child.mesh.add_edge(V(0, 0, 0), V(5, 5, 5))
        layer.name = "Renamed"
        win.viewport.scene.plugin_data["demo"] = {"value": 3}
        if fail:
            raise ValueError("rollback")
        return True
    ExtensionApp(win, "demo").add_agent_tool("edit", edit, description="Edit", mutates=True)
    bridge.start()
    assert not _ask(bridge, "edit", {"fail": True})["ok"]
    assert child.name == "Child" and child.ifc["custom"]["a"] == 1
    assert child.mesh.capture_state() == original
    assert layer.name == "Walls" and not win.viewport.scene.plugin_data
    assert call(bridge, "edit")
    call(bridge, "undo")
    assert child.name == "Child" and child.ifc["custom"]["a"] == 1
    assert child.mesh.capture_state() == original
    call(bridge, "redo")
    assert child.name == "Edited" and child.ifc["custom"]["a"] == 7


def test_noop_mutating_tool_preserves_redo(model):
    win, bridge, *_ = model
    app = ExtensionApp(win, "demo")
    app.add_agent_tool("nothing", lambda: None, description="Nothing", mutates=True)
    before = len(win.viewport.history.undo_stack)
    assert call(bridge, "nothing") is None
    assert len(win.viewport.history.undo_stack) == before
