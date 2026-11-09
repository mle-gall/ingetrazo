# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Linked files (core/links.py): another .igz placed as a live reference —
tags brought in namespaced and filed, saved as a placeholder, filled again
from the source, overrides that survive the source's changes, packing."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core import links
from core.layers import Layer, folder_parent, layer_of
from core.scene import Scene
from formats import igz


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _source(path, faces=1, wood_visible=True):
    s = Scene()
    s.layer_folders = ["Structure"]
    s.layers.append(Layer("Wood", visible=wood_visible, folder="Structure",
                          color=(0.5, 0.3, 0.1)))
    for i in range(faces):
        f = s.mesh.add_face([V(i, 0), V(i + 1, 0), V(i + 1, 1), V(i, 1)])
        f.attrs = {"layer": "Wood"}
    igz.save_scene(s, path)
    return path


def _host_with_link(tmp_path, src):
    host = Scene()
    comp = links.make_link(host, src, host_path=tmp_path / "host.igz")
    host.groups.append(comp)
    return host, comp


def _faces(group):
    from core.group import iter_placements
    return sum(len(g.mesh.faces) for g, _m in iter_placements(group))


def test_linking_brings_the_tags_namespaced_in_their_folders(tmp_path):
    src = _source(tmp_path / "Site.igz")
    host, comp = _host_with_link(tmp_path, src)
    assert links.is_linked(comp) and comp.name == "Site"
    wood = host.layer("Site / Wood")
    assert wood is not None and wood.color == (0.5, 0.3, 0.1)
    assert wood.folder == "Site / Structure"
    assert folder_parent(host, "Site / Structure") == "Site"
    assert folder_parent(host, "Site") == links.LINKED_FOLDER
    assert host.layer("Wood") is None                # never mixed with ours
    from core.group import iter_placements
    names = {layer_of(f) for g, _m in iter_placements(comp)
             for f in g.mesh.faces}
    assert names == {"Site / Wood"}


def test_saved_as_a_placeholder_and_filled_again_on_open(tmp_path):
    src = _source(tmp_path / "Site.igz", faces=3)
    host, _comp = _host_with_link(tmp_path, src)
    path = tmp_path / "host.igz"
    igz.save_scene(host, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.link_errors == {}
    (g,) = links.linked_groups(back)
    assert _faces(g) == 3


def test_a_changed_source_reloads_into_every_copy(tmp_path):
    from core.group import copy_group
    src = _source(tmp_path / "Site.igz", faces=1)
    host, comp = _host_with_link(tmp_path, src)
    host.groups.append(copy_group(comp, V(10, 0)))
    _source(src, faces=4)
    links.reload(host, src, tmp_path / "host.igz")
    assert [_faces(g) for g in links.linked_groups(host)] == [4, 4]


def test_a_host_override_survives_the_source_and_can_be_cleared(tmp_path):
    src = _source(tmp_path / "Site.igz")
    host, _comp = _host_with_link(tmp_path, src)
    host.layer("Site / Wood").visible = False
    assert links.note_visibility(host, "Site / Wood", False)
    _source(src, wood_visible=True)
    links.reload(host, src)
    assert host.layer("Site / Wood").visible is False      # host's choice
    # Not overridden: the source's switch comes through.
    links.clear_overrides(host, src)
    assert host.layer("Site / Wood").visible is True
    _source(src, wood_visible=False)
    links.reload(host, src)
    assert host.layer("Site / Wood").visible is False
    assert not links.note_visibility(host, "Layer 0", False)   # host's own


def test_any_host_switch_counts_as_an_override(tmp_path):
    """Isolate, a saved view, the panel: not through note_visibility."""
    from core.layers import set_visible
    src = _source(tmp_path / "Site.igz")
    host, _comp = _host_with_link(tmp_path, src)
    set_visible(host, ["Site / Wood"], False)
    _source(src, faces=2)                  # any change to the source
    links.reload(host, src)
    assert host.layer("Site / Wood").visible is False


def test_packed_keeps_the_geometry_without_the_source(tmp_path):
    src = _source(tmp_path / "Site.igz", faces=2)
    host, _comp = _host_with_link(tmp_path, src)
    links.set_packed(host, src, True)
    path = tmp_path / "host.igz"
    igz.save_scene(host, path)
    src.unlink()
    back = Scene()
    igz.load_into(back, path)
    (g,) = links.linked_groups(back)
    assert _faces(g) == 2 and back.link_errors == {}


def test_a_missing_source_opens_empty_and_keeps_the_link(tmp_path):
    src = _source(tmp_path / "Site.igz")
    host, _comp = _host_with_link(tmp_path, src)
    path = tmp_path / "host.igz"
    igz.save_scene(host, path)
    src.unlink()
    back = Scene()
    igz.load_into(back, path)
    assert list(back.link_errors) and links.linked_groups(back)
    igz.save_scene(back, path)                       # the link is not lost
    again = Scene()
    igz.load_into(again, path)
    assert links.linked_groups(again)


def test_the_project_folder_can_move(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    src = _source(proj / "Site.igz")
    host = Scene()
    host.groups.append(links.make_link(host, src, host_path=proj / "h.igz"))
    igz.save_scene(host, proj / "h.igz")
    moved = tmp_path / "moved"
    proj.rename(moved)
    back = Scene()
    igz.load_into(back, moved / "h.igz")
    assert back.link_errors == {}
    (g,) = links.linked_groups(back)
    assert links.link_of(g)["path"] == str((moved / "Site.igz").resolve())


def test_a_cycle_is_refused(tmp_path):
    a, b = tmp_path / "A.igz", tmp_path / "B.igz"
    _source(a)
    sb = Scene()
    sb.groups.append(links.make_link(sb, a, host_path=b))
    igz.save_scene(sb, b)
    sa = Scene()
    sa.groups.append(links.make_link(sa, b, host_path=a))
    igz.save_scene(sa, a)                    # A now links B, which links A
    back = Scene()
    igz.load_into(back, a)
    assert any("links itself" in e for e in back.link_errors.values())


def test_a_document_cannot_link_itself(tmp_path):
    src = _source(tmp_path / "Site.igz")
    with pytest.raises(links.LinkError):
        links.make_link(Scene(), src, host_path=src)


def test_a_deferred_mesh_is_relabelled_without_being_built():
    """Big documents load their meshes deferred: linking relabels their
    tables, and a later build comes out with the same names."""
    import numpy as np
    from core.mesh import DeferredMesh, Mesh
    built = []

    def build(m):
        built.append(True)
        f = m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
        f.attrs = {"layer": "Wood"}

    mesh = Mesh()
    src = {"meta": {"face_attrs": [{"layer": "Wood"}],
                    "edge_layers": ["Wood"]},
           "counts": np.array([1, 1], dtype=np.int32),
           "face_attr": np.array([0, -1], dtype=np.int32),
           "edges": np.zeros((3, 2), dtype=np.int32),
           "layers": np.array([0, -1, -1], dtype=np.int32)}
    assert DeferredMesh.defer(mesh, build, 2, src)
    assert links._relabel_deferred(mesh, lambda n: links.tag_name(
        "/x/Site.igz", n))
    assert not built                                  # never built
    new = mesh.__dict__["_deferred_source"]
    table = new["meta"]["face_attrs"]
    assert [table[i]["layer"] for i in new["face_attr"]] == [
        "Site / Wood", "Site / Untagged"]
    names = new["meta"]["edge_layers"]
    assert [names[i] for i in new["layers"]] == [
        "Site / Wood", "Site / Untagged", "Site / Untagged"]
    assert src["meta"]["face_attrs"][0]["layer"] == "Wood"   # not shared
    # Built later: the same names.
    assert {layer_of(f) for f in mesh.faces} == {"Site / Wood"}
    assert built


def test_a_links_untagged_pieces_take_their_owners_tag_colour():
    """Linking renames the source's default tag to «<file> / Untagged»; for
    colour that stand-in reads as none, so a nested untagged piece takes
    its owner's tag, as in its own file — the facilities model came up in
    one green instead of its tags' colours (Maxence, 2026-11-09)."""
    from core.group import Group
    from core.layers import DEFAULT_LAYER, object_layer
    from core.materials import effective_attrs
    from core.mesh import Mesh
    owner = Group(Mesh(), name="Beam")
    owner.layer = "Site / Steel"
    piece = Group(Mesh(), name="Flange")
    piece.layer = "Site / Untagged"
    piece.owner = owner
    assert object_layer(piece) == "Site / Steel"
    top = Group(Mesh(), name="Loose")
    top.layer = "Site / Untagged"
    assert object_layer(top) == DEFAULT_LAYER
    tagged = Group(Mesh(), name="Rail")
    tagged.layer = "Site / Wood"
    tagged.owner = owner
    assert object_layer(tagged) == "Site / Wood"      # its own tag still wins
    paint = {"by_layer": {"Site / Steel": (1.0, 0.0, 0.0),
                          "Site / Untagged": (0.0, 1.0, 0.0)},
             "color": (1.0, 0.0, 0.0)}
    assert effective_attrs({"layer": "Site / Untagged"}, paint)["color"] == (1.0, 0.0, 0.0)
    assert effective_attrs({"layer": "Site / Steel"}, paint)["color"] == (1.0, 0.0, 0.0)
    assert effective_attrs({}, paint)["color"] == (1.0, 0.0, 0.0)
