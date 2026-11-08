# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp 2021+ tag folders: the folder manager (9B3A) openskp leaves
unread is decoded by ``formats.openskp_compat`` and rebuilt by the importer
as nested tag folders. The bytes here are written in the layout read from
real production files (see the notes above ``parse_tag_folders``)."""
from __future__ import annotations

import struct

from core.layers import folder_parent, folders_of
from core.scene import Scene
from formats.openskp_compat import parse_tag_folders
from formats.skp import _import_tag_folders


def rec(tag: str, payload: bytes) -> bytes:
    return bytes.fromhex(tag) + struct.pack("<I", len(payload)) + payload


def var_id(n: int) -> bytes:
    """An id as the files store a small one: DE05, length, the var-int."""
    body = bytes([n])                 # < 0x80: a one-byte var-int
    return bytes([0xDE, 0x05]) + struct.pack("<I", len(body)) + body


def folder(key, name, tags=(), subs=(), hidden=False) -> bytes:
    ids = b"".join(bytes([1, t]) for t in tags)
    return rec("803E", rec("DC05", var_id(key)) + rec("813E", name.encode())
               + rec("833E", b"".join(subs)) + rec("843E", ids)
               + rec("823E", b"\x01" if hidden else b"\x00")
               + rec("853E", b"\x00"))


def manager() -> bytes:
    """Root › BUILDING › Dome › (tags 5, 6); Root › Hidden stuff (tag 7,
    hidden); the root itself files tag 9 (no folder)."""
    dome = folder(12, "Dome", tags=(5, 6))
    building = folder(11, "BUILDING", subs=(dome,))
    hidden = folder(13, "Hidden stuff", tags=(7,), hidden=True)
    root = rec("803E", rec("813E", b"") + rec("833E", building + hidden)
               + rec("843E", bytes([1, 9])) + rec("823E", b"\x00"))
    return root


def test_the_folder_tree_is_decoded_depth_first():
    fs = parse_tag_folders(manager())
    assert [f["name"] for f in fs] == ["BUILDING", "Dome", "Hidden stuff"]
    by = {f["name"]: f for f in fs}
    assert by["BUILDING"]["parent"] is None
    assert by["Dome"]["parent"] == by["BUILDING"]["key"]
    assert by["Dome"]["tags"] == [5, 6]
    assert by["Hidden stuff"]["hidden"] and not by["Dome"]["hidden"]


def test_garbage_never_raises():
    assert parse_tag_folders(b"") == []
    assert parse_tag_folders(b"\x80\x3e\xff\xff\xff\x7f") == []


def _records():
    names = {5: "Dome - Roof", 6: "Dome - Frame", 7: "Old mesh"}
    out = []
    for f in parse_tag_folders(manager()):
        out.append({"key": str(f["key"]), "name": f["name"],
                    "parent": None if f["parent"] is None
                    else str(f["parent"]),
                    "hidden": f["hidden"],
                    "tags": [names[t] for t in f["tags"] if t in names]})
    return out


def test_the_importer_nests_the_folders_and_files_the_tags():
    scene = Scene()
    folder_of, hidden = _import_tag_folders(scene, _records())
    assert folders_of(scene) == ["BUILDING", "Dome", "Hidden stuff"]
    assert folder_parent(scene, "Dome") == "BUILDING"
    assert folder_of["Dome - Roof"] == "Dome"
    assert hidden == {"Dome - Roof": False, "Dome - Frame": False,
                      "Old mesh": True}


def test_a_reimport_reuses_the_folders():
    scene = Scene()
    _import_tag_folders(scene, _records())
    _import_tag_folders(scene, _records())
    assert folders_of(scene) == ["BUILDING", "Dome", "Hidden stuff"]


def test_a_name_taken_elsewhere_gets_a_folder_of_its_own():
    scene = Scene()
    scene.layer_folders = ["Dome"]                 # a top-level «Dome» here
    folder_of, _h = _import_tag_folders(scene, _records())
    assert folder_of["Dome - Roof"] != "Dome"
    assert folder_parent(scene, folder_of["Dome - Roof"]) == "BUILDING"


def test_load_creates_the_tags_in_their_folders(monkeypatch):
    """Through the importer's payload path (formats.skp)."""
    from core.layers import Layer  # noqa: F401
    scene = Scene()
    payload_layers = [{"name": "Dome - Roof", "visible": True},
                      {"name": "Old mesh", "visible": True},
                      {"name": "Loose", "visible": False}]
    from formats import skp
    folder_of, hidden = skp._import_tag_folders(scene, _records())
    # The same steps load_skp takes for payload["layers"].
    from core.layers import Layer as L
    for raw in payload_layers:
        scene.layers.append(L(raw["name"],
                              visible=raw["visible"]
                              and not hidden.get(raw["name"], False),
                              folder=folder_of.get(raw["name"])))
    assert scene.layer("Dome - Roof").folder == "Dome"
    assert not scene.layer("Old mesh").visible          # its folder is hidden
    assert scene.layer("Loose").folder is None
