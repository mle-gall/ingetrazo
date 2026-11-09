# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Purge unused — "Purgar sin usar", for layers and materials.

A layer is a LABEL an entity carries, never its owner (see core.layers), so
deleting the geometry cannot delete the tag: the layer you empty on purpose
to refill it must survive, and undo would have to resurrect it otherwise.
What every CAD offers instead is an explicit sweep, and this is ours.

It matters most right after an import. Marco brought a surveyed plaza in as
a reference, kept one flat drawing as a guide and deleted the rest — and the
document still carried the 13 layers and 47 materials of the big drawing,
invisible (the Materials panel builds its "In model" swatches from painted
faces, not from the registry) but saved into every ``.igz`` from then on.

The traversal descends into nested placements. ``Group.children`` are real
geometry that renders, picks and exports as part of its parent, so a name
used only inside one is IN USE — a sweep that walked ``scene.groups`` as a
flat list would delete a layer out from under a component's insides.
"""
from __future__ import annotations

from core.layers import DEFAULT_LAYER, layer_of


def iter_groups(groups):
    """Distinct placements in document order, including hidden groups.

    Only identity and membership matter here. A shared subtree need only be
    visited once, and composing every placement's world matrix is unnecessary.
    """
    stack = list(groups or ())
    stack.reverse()
    seen = set()
    while stack:
        group = stack.pop()
        if id(group) in seen:
            continue
        seen.add(id(group))
        yield group
        stack.extend(reversed(getattr(group, "children", None) or ()))


def _document_groups(scene) -> list:
    """The groups in the model plus the component definitions kept in the
    file with no copy placed (``scene.kept_components``): a material or a
    layer only a kept definition wears is still in use — purging it would
    strip the definition the user asked to keep."""
    return (list(getattr(scene, "groups", None) or ())
            + list(getattr(scene, "kept_components", None) or ()))


def iter_meshes(scene):
    """The loose mesh plus every group's mesh, each distinct mesh once.

    ``scene.loose_mesh`` rather than ``scene.mesh``: inside an open group
    edit the two differ, and sweeping the model while the user is in a group
    must still see the geometry they left outside.
    """
    seen: set[int] = set()
    meshes = [scene.loose_mesh]
    meshes += [g.mesh for g in iter_groups(_document_groups(scene))]
    for m in meshes:
        if m is not None and id(m) not in seen:
            seen.add(id(m))
            yield m


def _annotations(scene):
    for coll in ("dimensions", "text_labels", "image_planes",
                 "section_planes", "guides"):
        yield from (getattr(scene, coll, None) or ())


def layer_carriers(scene):
    """Every entity in the document that can carry a layer label: faces and
    edges of every mesh, every group (nested placements and kept definitions
    included), the annotations and the photogrammetric survey. What renaming
    or deleting a layer has to relabel — missing one leaves it tagged with a
    name that no longer exists."""
    for mesh in iter_meshes(scene):
        yield from mesh.faces
        yield from mesh.edges
    yield from iter_groups(_document_groups(scene))
    yield from _annotations(scene)
    photo = getattr(scene, "photo_mesh", None)
    if photo is not None:
        yield photo


def _count_edges(src, tally):
    """Count the same welded keys as lazy_mesh.plan, including ring-only edges."""
    import numpy as np
    from core.lazy_mesh import weld

    vertices, inverse = weld(src["pos"])

    def keys(a, b):
        return np.minimum(a, b) * len(vertices) + np.maximum(a, b)

    a, b = inverse[src["edges"]].T
    keep = a != b
    explicit = keys(a[keep], b[keep])
    corners = inverse[src["rings"]]
    boundary = np.empty(0, dtype=np.int64)
    if len(corners):
        ends = np.cumsum(src["sizes"])
        following = np.roll(corners, -1)
        following[ends - 1] = corners[ends - src["sizes"]]
        boundary = keys(corners, following)
    total = len(np.unique(np.concatenate((explicit, boundary))))
    layers = src["layers"]
    if layers is not None and src["flags"] is not None:
        labels = layers[keep]
        named = labels >= 0
        # Last assigned (nonnegative) layer wins for a repeated edge.
        _, last = np.unique(explicit[named][::-1], return_index=True)
        names = src["meta"].get("edge_layers") or ()
        for i, n in enumerate(np.bincount(labels[named][::-1][last])):
            if n:
                tally[names[i]] += int(n)
        total -= len(last)
    if total:
        tally[None] += total


def layer_counts(scene, *, photo: bool = True) -> dict[str, int]:
    """Count every layer carrier, yielding the same counts as the panel."""
    return next(counts for counts in layer_count_steps(scene, photo=photo)
                if counts is not None)


def layer_count_steps(scene, *, photo=True):
    """Yield between meshes and group batches, then publish one complete tally."""
    from collections import Counter
    import numpy as np
    tally = Counter()
    seen = set()

    def count_mesh(mesh):
        if mesh is None or id(mesh) in seen:
            return
        seen.add(id(mesh))
        src = mesh.__dict__.get("_deferred_source")
        if src is None:
            tally.update(layer_of(f) for f in mesh.faces)
            tally.update(layer_of(e) for e in mesh.edges)
            return
        _count_edges(src, tally)
        face_attr = src.get("face_attr")
        if face_attr is None:
            tally[None] += len(src["counts"])
            return
        # One pass over the face → attribute-row index (14 M faces on the
        # plant of #158: a Python loop per face was 0.5 s on every edit).
        table = src["meta"].get("face_attrs") or []
        rows = np.asarray(face_attr)
        per_row = np.bincount(rows[rows >= 0], minlength=len(table))
        tally[None] += int(rows.size - per_row.sum())
        for raw, n in zip(table, per_row.tolist()):
            if n:
                tally[(raw or {}).get("layer")] += n
    count_mesh(scene.loose_mesh)
    yield None
    for i, group in enumerate(iter_groups(_document_groups(scene))):
        tally[layer_of(group)] += 1
        if id(group.mesh) not in seen:
            count_mesh(group.mesh)
            yield None
        elif i % 256 == 0:
            yield None
    counts: dict[str, int] = {}

    def add(name, n=1):
        name = name or DEFAULT_LAYER
        counts[name] = counts.get(name, 0) + n

    for name, n in tally.items():
        add(name, n)
    for ent in _annotations(scene):
        add(layer_of(ent))
    survey = getattr(scene, "photo_mesh", None) if photo else None
    if survey is not None:
        add(layer_of(survey))
    yield counts


def used_layers(scene) -> set[str]:
    """Every layer name something in the document carries — counted as the
    Layers panel counts, so a lazy group mesh is not built to answer (the
    «In use» and «Unused» filters ask on every edit). The survey's layer is
    left out, as it always was."""
    return {DEFAULT_LAYER} | set(layer_counts(scene, photo=False))


def layers_held_by_scenes(scene) -> set[str]:
    """Layer names a saved view switches off.

    An empty layer a scene deliberately hides is not litter — it is part of
    that scene's meaning, and modellers build plan/elevation scenes
    around tags they are about to fill. The sweep leaves them alone and says
    so, rather than quietly breaking a view.
    """
    held: set[str] = set()
    for view in getattr(scene, "saved_views", None) or ():
        held.update(getattr(view, "hidden_layers", None) or ())
    return held


def unused_layers(scene) -> list:
    """The :class:`core.layers.Layer` objects a purge would remove."""
    keep = used_layers(scene) | layers_held_by_scenes(scene)
    return [ly for ly in getattr(scene, "layers", None) or ()
            if ly.name != DEFAULT_LAYER and ly.name not in keep]


def used_materials(scene) -> set[str]:
    """Every registry material name a face wears (``attrs["mat"]``)."""
    used: set[str] = set()
    for mesh in iter_meshes(scene):
        for f in mesh.faces:
            name = f.attrs.get("mat")
            if name:
                used.add(name)
    # A group's own paint (issue #47) lives on the group, not on its faces:
    # Purge used to delete a material that only a group wore (issue #133).
    from core.group import iter_placements
    for top in _document_groups(scene):
        for g, _m in iter_placements(top):
            paint = getattr(g, "material", None) or {}
            if paint.get("mat"):
                used.add(paint["mat"])
    return used


def unused_materials(scene) -> list[str]:
    """Registry material names no face wears, in registry order."""
    used = used_materials(scene)
    return [n for n in getattr(scene, "materials", None) or () if n not in used]
