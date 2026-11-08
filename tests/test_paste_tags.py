# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A copy carries its tags: pasted into another document, the geometry
keeps its tags — created there with their colour and folder when missing,
left alone when the document already has them — and undo takes the new
tags away with the paste."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import History
from core.insert import used_layers
from core.layers import (Layer, add_missing, folder_parent, folders_of,
                         layer_of, template_for)
from core.mesh import Mesh
from core.scene import Scene
from tools.paste import PasteTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _VP:
    def __init__(self, scene, clipboard):
        self.scene, self.clipboard = scene, clipboard
        self.history = History(scene)

    def update(self):
        pass


def _source():
    """A document with a face on «Wood» (in «Building › Structure»), a
    loose edge on «Axes» and a group on «Furniture»."""
    s = Scene()
    s.layer_folders = ["Building", "Structure"]
    s.folder_parents = {"Structure": "Building"}
    s.layers += [Layer("Wood", color=(0.6, 0.4, 0.2), folder="Structure"),
                 Layer("Axes", visible=False),
                 Layer("Furniture", locked=True),
                 Layer("Unused")]
    return s


def _clip(src):
    face = ([V(0, 0), V(1, 0), V(1, 1), V(0, 1)], [], {"layer": "Wood"})
    m = Mesh()
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    g = Group(m, "Bench")
    g.layer = "Furniture"
    edge_layers = ["Axes"]
    names = used_layers([face[2]], edge_layers, [g])
    return {"faces": [face], "edges": [(V(3, 0), V(4, 0), False, None)],
            "edge_layers": edge_layers,
            "layers": template_for(src, names),
            "groups": [g], "ref": V(0, 0, 0)}


def test_the_copy_names_only_the_tags_it_uses():
    clip = _clip(_source())
    names = [d["name"] for d in clip["layers"]["layers"]]
    assert names == ["Wood", "Axes", "Furniture"]        # «Unused» stays home
    assert clip["layers"]["folders"] == ["Building", "Structure"]
    assert clip["layers"]["folder_parents"] == {"Structure": "Building"}


def test_paste_brings_missing_tags_with_their_folders_and_undo_removes_them():
    dst = Scene()
    vp = _VP(dst, _clip(_source()))
    assert PasteTool.in_place(vp)
    wood = dst.layer("Wood")
    assert wood is not None and wood.folder == "Structure"
    assert wood.color == (0.6, 0.4, 0.2)
    assert folder_parent(dst, "Structure") == "Building"
    # Pasted geometry shows: a tag hidden or locked at home arrives usable.
    assert dst.layer("Axes").visible and not dst.layer("Furniture").locked
    assert dst.layer("Unused") is None
    assert any(layer_of(f) == "Wood" for f in dst.mesh.faces)
    assert any(layer_of(e) == "Axes" for e in dst.mesh.edges)
    assert dst.groups[-1].layer == "Furniture"

    assert vp.history.undo()
    assert dst.layer("Wood") is None and dst.layer("Axes") is None
    assert folders_of(dst) == []


def test_a_tag_the_document_has_keeps_its_own_look():
    dst = Scene()
    dst.layers.append(Layer("Wood", visible=False, color=(0.1, 0.1, 0.9)))
    vp = _VP(dst, _clip(_source()))
    assert PasteTool.in_place(vp)
    wood = dst.layer("Wood")
    assert wood.color == (0.1, 0.1, 0.9) and not wood.visible
    assert wood.folder is None
    assert vp.history.undo()
    assert dst.layer("Wood") is not None              # it was never ours


def test_add_missing_never_moves_an_existing_folder():
    dst = Scene()
    dst.layer_folders = ["Structure"]                  # a top-level one here
    add_missing(dst, template_for(_source(), ["Wood"]))
    assert folder_parent(dst, "Structure") is None
    assert "Building" in folders_of(dst)


def test_the_tags_survive_the_system_clipboard():
    from formats import clip as transfer
    back = transfer.decode(transfer.encode(_clip(_source())))
    assert back is not None
    assert back["edge_layers"] == ["Axes"]
    names = {d["name"]: d for d in back["layers"]["layers"]}
    assert names["Wood"]["folder"] == "Structure"
    assert back["layers"]["folder_parents"] == {"Structure": "Building"}
    dst = Scene()
    assert PasteTool.in_place(_VP(dst, back))
    assert dst.layer("Wood") is not None and dst.layer("Axes") is not None
