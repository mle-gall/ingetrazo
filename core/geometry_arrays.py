# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure placed geometry without allocating Python vertices or faces.

Rings retain their winding and holes. Independently closed placements retain their topology. Open placements weld
together because an object can be assembled from individually open shells.
"""
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Arrays:
    pos: np.ndarray
    corners: np.ndarray
    ring_sizes: np.ndarray
    ring_counts: np.ndarray
    edge_face_counts: np.ndarray | None = None
    _perimeter: float = field(default=0., init=False, repr=False)
    _balanced: bool = field(default=True, init=False, repr=False)
    _signed_volume: float = field(default=0., init=False, repr=False)
    _bounds: object = field(default=None, init=False, repr=False)
    _measurements: object = field(default=None, init=False, repr=False)


def faces_arrays(faces):
    """Extract legacy faces once, preserving shared vertex identity."""
    vertices, lookup, corners, sizes, counts = [], {}, [], [], []
    for face in faces:
        loops = (face.loop, *face.hole_loops)
        counts.append(len(loops))
        for loop in loops:
            sizes.append(len(loop))
            for vertex in loop:
                key = id(vertex)
                if key not in lookup:
                    lookup[key] = len(vertices)
                    p = vertex.position
                    vertices.append((p.x(), p.y(), p.z()))
                corners.append(lookup[key])
    return Arrays(np.asarray(vertices, dtype=float).reshape(-1, 3),
                  np.asarray(corners, dtype=np.int64),
                  np.asarray(sizes, dtype=np.int64),
                  np.asarray(counts, dtype=np.int64))


def arrays_of(mesh):
    d = mesh.__dict__
    serial = (d.get('_mut_serial'), id(d.get('_deferred_source')))
    cached = d.get('_geometry_arrays')
    if cached is None or cached[0] != serial:
        source = d.get('_deferred_source')
        if source is not None:
            # Saved indexed topology is authoritative: coincident distinct
            # points stay distinct. JSON sources instead repeat coordinates.
            pos = np.asarray(source['pos'], dtype=np.float32).astype(float)
            corners = np.asarray(source['rings'], dtype=np.int64)
            if 'sequential' in source and 'arrays' not in source.get('meta', {}):
                from core.lazy_mesh import weld
                pos, inverse = weld(pos, source['sequential'])
                corners = inverse[corners]
            arrays = Arrays(pos, corners, np.asarray(source['sizes'], dtype=np.int64),
                            np.asarray(source['counts'], dtype=np.int64))
            arrays.edge_face_counts = edge_counts(arrays)
        else:
            arrays = faces_arrays(mesh.faces)
            arrays.edge_face_counts = np.asarray([len(e.faces) for e in mesh.edges])
        cached = (serial, arrays)
        d['_geometry_arrays'] = cached
    return cached[1]


def edge_counts(a):
    """Count ring incidences by saved point identity, ignoring loose edges."""
    if not len(a.corners):
        return np.empty(0, dtype=np.int64)
    ends = np.cumsum(a.ring_sizes)
    nxt = np.arange(len(a.corners)) + 1
    nxt[ends - 1] = ends - a.ring_sizes
    edges = np.sort(np.column_stack((a.corners, a.corners[nxt])), axis=1)
    keys = edges[:, 0] * np.int64(len(a.pos)) + edges[:, 1]
    return np.unique(keys, return_counts=True)[1]


def owned_placements(group, base=None, excluded=()):
    """Iterative equivalent of iter_placements, pruning other objects early."""
    from core.bim import _compose
    stack = [(group, base)]
    while stack:
        placed, parent = stack.pop()
        matrix = _compose(parent, getattr(placed, 'xform', None))
        yield placed, matrix
        stack.extend((child, matrix) for child in reversed(placed.children or ())
                     if not child.ifc and child.uid not in excluded)


def uniform_scale(local, rot, trans):
    """Uniform scale when float32 rounding stays below quantity tolerance.

    Thin solids far from the origin need the historical world calculation.
    A surface-area times coordinate-error bound guards their signed volume;
    this also avoids magnifying cancellation in almost-zero volumes.
    """
    gram = rot.T @ rot
    scale2 = float(np.trace(gram) / 3)
    if scale2 <= 0 or np.max(np.abs(gram - np.eye(3) * scale2)) > 2e-6 * scale2:
        return None
    data = measurements(local)
    if data is not None:
        bounds = np.maximum(np.abs(local._bounds[0]), np.abs(local._bounds[1]))
        magnitude = float(np.max(np.abs(rot) @ bounds + np.abs(trans)))
        error = magnitude * np.finfo(np.float32).eps
        area = float(data[0].sum()) * scale2
        if error * local._perimeter * scale2**.5 > max(1e-7, 2e-5 * area):
            return None
        if data[4]:
            volume = data[3] * abs(float(np.linalg.det(rot)))
            if error * area > max(1e-7, 2e-5 * volume):
                return None
    return scale2


def placed_arrays(local, matrix):
    """Reuse prototype Newell measurements for rigid/uniform placements.

    General affine transforms retain the full transformed-position calculation.
    Uniformity is relative to scale, so tiny anisotropic matrices cannot pass.
    """
    if matrix is None:
        return local
    from core.group import np_affine
    rot, trans = np_affine(matrix)
    a = Arrays((local.pos @ rot.T + trans).astype(np.float32).astype(float),
               local.corners, local.ring_sizes, local.ring_counts,
               local.edge_face_counts)
    scale2 = uniform_scale(local, rot, trans)
    if scale2 is not None:
        data = measurements(local)
        if data is not None:
            gross, net, normals, volume, closed, starts = data
            det = float(np.linalg.det(rot))
            a._measurements = (gross * scale2, net * scale2,
                               np.sign(det) * (normals @ rot.T) / scale2**.5,
                               None if volume is None else volume * abs(det),
                               closed, starts)
    return a


def world_arrays(group, base=None, excluded=(), placements=None):
    """Yield owned arrays from a reusable list of composed placements."""
    if placements is None:
        placements = owned_placements(group, base, excluded)
    for placed, matrix in placements:
        arrays = arrays_of(placed.mesh)
        if len(arrays.ring_counts):
            yield placed_arrays(arrays, matrix)


def merged(arrays):
    """Join and weld placements with the engine's position tolerance."""
    from core.lazy_mesh import weld
    parts = list(arrays)
    if not parts:
        return faces_arrays([])
    offsets = np.cumsum([0] + [len(a.pos) for a in parts[:-1]])
    pos, inverse = weld(np.concatenate([a.pos for a in parts]))
    corners = np.concatenate([a.corners + offset for a, offset in zip(parts, offsets)])
    return Arrays(pos, inverse[corners], np.concatenate([a.ring_sizes for a in parts]),
                  np.concatenate([a.ring_counts for a in parts]))


def assembled(arrays):
    """Avoid a position weld when placement topology already answers closure."""
    parts = list(arrays)
    if not parts:
        return faces_arrays([])
    if len(parts) == 1:
        return parts[0]
    if not all(a.edge_face_counts is not None and
               np.all((a.edge_face_counts == 0) | (a.edge_face_counts == 2)) for a in parts):
        return merged(parts)
    offsets = np.cumsum([0] + [len(a.pos) for a in parts[:-1]])
    return Arrays(np.concatenate([a.pos for a in parts]),
                  np.concatenate([a.corners + off for a, off in zip(parts, offsets)]),
                  np.concatenate([a.ring_sizes for a in parts]),
                  np.concatenate([a.ring_counts for a in parts]),
                  np.concatenate([a.edge_face_counts for a in parts]))


def ring_data(a):
    starts = np.r_[0, np.cumsum(a.ring_sizes)[:-1]]
    nxt = np.arange(len(a.corners)) + 1
    nxt[starts + a.ring_sizes - 1] = starts
    # Subtract in float64 before products, avoiding cancellation far from origin.
    points = a.pos[a.corners] - a.pos[a.corners[0]]
    vectors = .5 * np.add.reduceat(np.cross(points, points[nxt]), starts, axis=0)
    return starts, nxt, points, vectors


def measurements(a):
    """Cached metrics for read-only arrays, shared by IFC body, Qto and paint.

    Mesh edits replace the array bundle through its mutation serial; consumers
    must treat these arrays as read-only, just like a deferred Plan.
    """
    if a._measurements is not None:
        return a._measurements
    if not len(a.ring_counts):
        return None
    starts, nxt, points, vectors = ring_data(a)
    outer = np.r_[0, np.cumsum(a.ring_counts)[:-1]]
    ring_areas = np.linalg.norm(vectors, axis=1)
    gross = ring_areas[outer]
    net = np.maximum(2 * gross - np.add.reduceat(ring_areas, outer), 0)
    counts = a.edge_face_counts
    if counts is None:
        edges = np.sort(np.column_stack((a.corners, a.corners[nxt])), axis=1)
        keys = edges[:, 0] * np.int64(len(a.pos)) + edges[:, 1]
        _, counts = np.unique(keys, return_counts=True)
    closed = bool(np.any(counts) and np.all((counts == 0) | (counts == 2)))
    # Triangulation subtracts holes regardless of their stored winding.
    owners = np.repeat(np.arange(len(outer)), a.ring_counts)
    same = np.einsum('ij,ij->i', vectors, vectors[outer][owners]) > 0
    same[outer] = False
    signed = np.where(same[:, None], -vectors, vectors)
    volume = (abs(float(np.sum(np.einsum('ij,ij->i', points[starts], signed)) / 3))
              if closed else None)
    a._perimeter = float(np.linalg.norm(points - points[nxt], axis=1).sum())
    a._balanced = bool(np.linalg.norm(signed.sum(axis=0)) <= 1e-10 * ring_areas.sum())
    if closed:
        a._signed_volume = float(np.sum(np.einsum('ij,ij->i', points[starts], signed)) / 3)
    used = a.pos[a.corners]
    a._bounds = (used.min(axis=0), used.max(axis=0))
    normals = vectors[outer] / np.maximum(gross[:, None], 1e-300)
    a._measurements = gross, net, normals, volume, closed, starts[outer]
    return a._measurements


def quantities(arrays):
    a = arrays if isinstance(arrays, Arrays) else assembled(arrays)
    data = measurements(a)
    if data is None:
        return 0., 0., None, False, 0
    gross, net, _, volume, closed, _ = data
    return float(gross.sum()), float(net.sum()), volume, closed, len(gross)


def placement_quantities(placements):
    """Measure prototypes once; only open assemblies need world welding."""
    parts = [(arrays_of(g.mesh), matrix) for g, matrix in placements]
    parts = [(a, m) for a, m in parts if len(a.ring_counts)]
    if not parts:
        return 0., 0., None, False, 0
    local = [measurements(a) for a, _ in parts]
    if len(parts) > 1 and not all(data[4] and a._balanced
                                  for (a, _), data in zip(parts, local)):
        return quantities(placed_arrays(a, m) for a, m in parts)
    gross = net = signed_volume = 0.
    count = 0
    from core.group import np_affine
    for (a, matrix), data in zip(parts, local):
        det = scale2 = 1.
        if matrix is not None:
            rot, trans = np_affine(matrix)
            scale2 = uniform_scale(a, rot, trans)
            det = float(np.linalg.det(rot))
            if scale2 is None:
                return quantities(placed_arrays(a, m) for a, m in parts)
        gross += float(data[0].sum()) * scale2
        net += float(data[1].sum()) * scale2
        signed_volume += a._signed_volume * det
        count += len(data[0])
    closed = all(data[4] for data in local)
    return gross, net, abs(signed_volume) if closed else None, closed, count


def face_attributes(mesh):
    """Every face's metadata in ring order (face_attrs only yields distinct sets)."""
    from core.mesh import DeferredMesh
    if type(mesh) is DeferredMesh:
        from formats.igz import _face_attrs_from_json
        src = mesh.__dict__['_deferred_source']
        table = [_face_attrs_from_json(a) or {} for a in src['meta'].get('face_attrs') or []]
        return [table[k] if k >= 0 else {} for k in src['face_attr']]
    return [f.attrs for f in mesh.faces]


def recorded_arrays(faces):
    """Opening records already contain coordinates; do not build a temporary mesh."""
    rings = [loop for face in faces for loop in (face['outer'], *face.get('holes', []))]
    sizes = np.asarray([len(loop) for loop in rings], dtype=np.int64)
    pos = np.asarray([p for loop in rings for p in loop], dtype=float).reshape(-1, 3)
    counts = np.asarray([1 + len(face.get('holes', [])) for face in faces], dtype=np.int64)
    return merged([Arrays(pos, np.arange(len(pos)), sizes, counts)])


def selected_arrays(mesh, indices, matrix=None):
    """World geometry of a face-tagged subset inside a placed definition."""
    a = arrays_of(mesh)
    mask = np.zeros(len(a.ring_counts), dtype=bool)
    mask[indices] = True
    rings = np.repeat(mask, a.ring_counts)
    corners = np.repeat(rings, a.ring_sizes)
    # Unselected vertices must not influence the subset's weld.
    pos = a.pos[a.corners[corners]]
    if matrix is not None:
        from core.group import np_affine
        rot, trans = np_affine(matrix)
        pos = (pos @ rot.T + trans).astype(np.float32).astype(float)
    return merged([Arrays(pos, np.arange(len(pos)), a.ring_sizes[rings],
                          a.ring_counts[mask])])
