# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure placed geometry without allocating Python vertices or faces.

Rings retain their winding and holes. Closure is checked after welding all
placements, because an object can be assembled from individually open shells.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class Arrays:
    pos: np.ndarray
    corners: np.ndarray
    ring_sizes: np.ndarray
    ring_counts: np.ndarray
    edge_face_counts: np.ndarray | None = None


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
    from core.lazy_mesh import plan_of
    plan = plan_of(mesh)
    if plan is not None:
        return Arrays(plan.pos, plan.corners, plan.ring_sizes, plan.ring_counts,
                      np.diff(plan.ef_start))
    serial = getattr(mesh, '_mut_serial', None)
    cached = mesh.__dict__.get('_geometry_arrays')
    if cached is None or cached[0] != serial:
        arrays = faces_arrays(mesh.faces)
        arrays.edge_face_counts = np.asarray([len(e.faces) for e in mesh.edges])
        cached = (serial, arrays)
        mesh.__dict__['_geometry_arrays'] = cached
    return cached[1]


def world_arrays(group, base=None, excluded=()):
    """Yield owned placements, pruning tagged descendants and openings."""
    from core.group import np_affine
    from core.bim import _compose
    matrix = _compose(base, getattr(group, 'xform', None))
    arrays = arrays_of(group.mesh)
    if len(arrays.ring_counts):
        if matrix is not None:
            rot, trans = np_affine(matrix)
            arrays = Arrays((arrays.pos @ rot.T + trans).astype(np.float32).astype(float),
                            arrays.corners, arrays.ring_sizes, arrays.ring_counts)
        yield arrays
    for child in getattr(group, 'children', None) or ():
        if not child.ifc and child.uid not in excluded:
            yield from world_arrays(child, matrix, excluded)


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


def ring_data(a):
    starts = np.r_[0, np.cumsum(a.ring_sizes)[:-1]]
    nxt = np.arange(len(a.corners)) + 1
    nxt[starts + a.ring_sizes - 1] = starts
    # Subtract in float64 before products, avoiding cancellation far from origin.
    points = a.pos[a.corners] - a.pos[a.corners[0]]
    vectors = .5 * np.add.reduceat(np.cross(points, points[nxt]), starts, axis=0)
    return starts, nxt, points, vectors


def measurements(a):
    """Reusable face metrics for takeoff classes, without face proxies."""
    if not len(a.ring_counts):
        return None
    starts, nxt, points, vectors = ring_data(a)
    outer = np.r_[0, np.cumsum(a.ring_counts)[:-1]]
    ring_areas = np.linalg.norm(vectors, axis=1)
    gross = ring_areas[outer]
    net = np.maximum(2 * gross - np.add.reduceat(ring_areas, outer), 0)
    edges = np.sort(np.column_stack((a.corners, a.corners[nxt])), axis=1)
    # Integer keys avoid the structured-array sort of unique(axis=0).
    keys = edges[:, 0] * np.int64(len(a.pos)) + edges[:, 1]
    _, counts = np.unique(keys, return_counts=True)
    closed = bool(np.all(counts == 2))
    # Triangulation subtracts holes regardless of their stored winding.
    owners = np.repeat(np.arange(len(outer)), a.ring_counts)
    same = np.einsum('ij,ij->i', vectors, vectors[outer][owners]) > 0
    same[outer] = False
    signed = np.where(same[:, None], -vectors, vectors)
    volume = (abs(float(np.sum(np.einsum('ij,ij->i', points[starts], signed)) / 3))
              if closed else None)
    normals = vectors[outer] / np.maximum(gross[:, None], 1e-300)
    return gross, net, normals, volume, closed, starts[outer]


def quantities(arrays):
    a = arrays if isinstance(arrays, Arrays) else merged(arrays)
    data = measurements(a)
    if data is None:
        return 0., 0., None, False, 0
    gross, net, _, volume, closed, _ = data
    return float(gross.sum()), float(net.sum()), volume, closed, len(gross)


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
