# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The parts of a component, measured the way a cut list measures them.

A container's children are its parts (a stool split into its pieces, a
cabinet drawn board by board). For each one this module answers what the
Parts tray shows: its name, the material most of it wears, and its size as
length × width × thickness — the box a woodworker would cut it from, not
the box its axes happen to give. A leg splayed at 10° measured along the
stool's own axes is a fat diagonal; measured along its own length it is
the 4 × 4 × 58 cm stick it is.

Nothing here touches the scene: the tray reads, and every change goes
through a command.
"""
from __future__ import annotations

from pathlib import PurePath


def part_points(part):
    """``part``'s vertex positions in its container's coordinates, as an
    ``(N, 3)`` float64 array (its nested placements included)."""
    from core.group import placement_points
    return placement_points(part)


#: How much smaller the part's own box must be to beat the model's axes.
_OWN_AXES_GAIN = 0.8


def part_size(points) -> tuple:
    """``(length, width, thickness)`` in metres, largest first: the extent
    of the tighter of two boxes — along the container's axes, or along the
    part's own principal axes. Either can win: a board lying square in a
    cabinet measures exactly on the cabinet's axes, a splayed leg only on
    its own."""
    import numpy as np
    if len(points) == 0:
        return (0.0, 0.0, 0.0)

    def extent(axes):
        proj = points @ axes.T
        return proj.max(axis=0) - proj.min(axis=0)

    best = extent(np.eye(3))
    if len(points) >= 4:
        centred = points - points.mean(axis=0)
        _w, vecs = np.linalg.eigh(centred.T @ centred)
        own = extent(vecs.T)
        # The part's own axes win only when they are MUCH tighter. A splayed
        # leg or a board lying at an angle is: its own box is a fraction of
        # the diagonal one. A stepped shape square to the model (a carcass
        # with a plinth set back) is not — a slightly tilted box happens to
        # hold it in 7 % less volume, and reads as a depth no one would cut.
        if np.prod(own) < _OWN_AXES_GAIN * np.prod(best):
            best = own
    dims = sorted((float(d) for d in best), reverse=True)
    return tuple(dims)


def _material_label(attrs) -> str | None:
    """What a face is painted with, as a person would name it: the
    registry name when the paint has one, else the texture's file name,
    else the colour. ``None`` for an unpainted face."""
    if not attrs:
        return None
    if attrs.get("mat"):
        return str(attrs["mat"])
    tex = attrs.get("texture")
    if tex and tex.get("path"):
        return PurePath(str(tex["path"])).stem
    col = attrs.get("color")
    if col is not None:
        r, g, b = (int(round(c * 255)) for c in list(col)[:3])
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _mesh_material_areas(mesh, inherited):
    """Material histogram of one prototype, without building lazy topology."""
    from core.materials import has_own_material
    from core.mesh import DeferredMesh
    area = {}
    if type(mesh) is DeferredMesh:
        import numpy as np
        from core.lazy_mesh import plan_of, face_net_areas
        from formats.igz import _face_attrs_from_json
        source = mesh.__dict__["_deferred_source"]
        table = source["meta"].get("face_attrs") or []
        keys = np.asarray(source["face_attr"], dtype=np.int64)
        plan = plan_of(mesh)
        geometry = mesh.__dict__.get("_deferred_geom")
        if geometry is not None and (plan.ring_counts == 1).all():
            # The renderer already computed these exact Qt-compatible
            # Newell lengths. With no holes, net area is half that length.
            values = 0.5 * geometry[1].astype(np.float64)
        else:
            values = face_net_areas(plan)
        totals = np.bincount(keys + 1, weights=values,
                             minlength=len(table) + 1)
        _, first = np.unique(keys, return_index=True)
        for key in keys[np.sort(first)].tolist():
            attrs = _face_attrs_from_json(table[key]) if key >= 0 else {}
            label = _material_label(attrs if has_own_material(attrs) else inherited)
            if label:
                area[label] = area.get(label, 0.0) + float(totals[key + 1])
    else:
        for f in mesh.faces:
            attrs = f.attrs if has_own_material(f.attrs) else inherited
            label = _material_label(attrs)
            if label:
                area[label] = area.get(label, 0.0) + f.net_area()
    return area


def part_material(part, cache=None) -> str:
    """The material covering most of ``part``'s surface ('' when none).
    A default face shows its container's paint, as it draws. Shared
    prototypes are measured once, rather than once for every placement."""
    from core.group import iter_placements
    if cache is None:
        cache = {}
    area = {}
    for g, _m in iter_placements(part):
        inherited = getattr(g, "material", None) or getattr(part, "material", None)
        key = (id(g.mesh), _material_label(inherited))
        hist = cache.get(key)
        if hist is None:
            hist = cache[key] = _mesh_material_areas(g.mesh, inherited)
        for label, value in hist.items():
            area[label] = area.get(label, 0.0) + value
    return max(area, key=area.get) if area else ""


def part_rows(container, material_cache=None) -> list:
    """One row per part of ``container``: ``{"part", "name", "material",
    "size", "faces"}``, in the container's order."""
    from core.group import iter_placements
    from core.mesh import face_count
    if material_cache is None:
        material_cache = {}
    rows = []
    for child in getattr(container, "children", None) or ():
        rows.append({
            "part": child,
            "name": child.name,
            "material": part_material(child, material_cache),
            "size": part_size(part_points(child)),
            "faces": sum(face_count(g.mesh) for g, _m in iter_placements(child)),
            "hidden": bool(getattr(child, "hidden", False)),
        })
    return rows


#: Thinner than this, a part is a SURFACE: a skin, a decal, a pane drawn as
#: one plane — geometry a person sees, with no thickness to cut (metres).
SURFACE_BELOW = 0.0005


def is_surface(size) -> bool:
    """Whether a part of ``size`` (length, width, thickness) has no real
    thickness. Such parts are kept — deleting them would leave a hole in
    what the model shows — but a cut list must not read them as boards."""
    return float(size[2]) < SURFACE_BELOW


def cut_list(rows, precision_mm: float = 1.0,
             by_material: bool = True) -> list:
    """Rows merged into cut-list lines: parts of the same size (to
    ``precision_mm``) — and, with ``by_material``, the same material — are
    one line with a quantity: two side legs are «2 × 58 × 45 × 4».

    ``by_material=False`` is for models whose paint says nothing about the
    wood: a Sweet Home 3D model gives every fragment its own texture image,
    so two identical legs never share a material there. Merged lines list
    every material they cover. Largest parts first."""
    lines: dict = {}
    for row in rows:
        size_key = tuple(round(d * 1000.0 / precision_mm)
                         for d in row["size"])
        key = ((row["material"],) if by_material else ()) + size_key
        line = lines.get(key)
        if line is None:
            lines[key] = {"names": [row["name"]],
                          "materials": [row["material"]],
                          "size": row["size"], "qty": 1}
        else:
            line["names"].append(row["name"])
            if row["material"] not in line["materials"]:
                line["materials"].append(row["material"])
            line["qty"] += 1
    for line in lines.values():
        line["names"].sort(key=_natural)
        line["material"] = ", ".join(m for m in line["materials"] if m)
    return sorted(lines.values(),
                  key=lambda ln: (tuple(-round(d, 6) for d in ln["size"]),
                                  _natural(ln["names"][0])))


def _natural(name: str) -> tuple:
    """Sort key that puts «Piece 2» before «Piece 10»."""
    import re
    return tuple(int(t) if t.isdigit() else t.lower()
                 for t in re.split(r"(\d+)", name))


def cut_list_text(lines, fmt_len, headers, surface: str = "surface") -> str:
    """The cut list as tab-separated text, one line per ``cut_list`` entry —
    what pastes straight into a spreadsheet. ``fmt_len`` formats a length in
    metres (the model's units); ``headers`` are the six column titles; a
    part with no thickness (:func:`is_surface`) reads ``surface`` in the
    thickness column instead of a zero."""
    out = ["\t".join(headers)]
    for ln in lines:
        length, width, thick = ln["size"]
        out.append("\t".join([str(ln["qty"]), ", ".join(ln["names"]),
                              ln["material"], fmt_len(length),
                              fmt_len(width),
                              surface if is_surface(ln["size"])
                              else fmt_len(thick)]))
    return "\n".join(out) + "\n"
