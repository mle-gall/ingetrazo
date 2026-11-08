"""Reuse exact snap rules with resident prototype candidates, never a GL bake.

Preparation owns only immutable packed arrays and runs away from Qt. Camera
changes do not invalidate the native prototype BVHs or placement transforms.
"""
from types import SimpleNamespace
import numpy as np
from PySide6.QtGui import QVector3D
from core import _native
from core.snap import compute_snap


def prepare(packed):
    native = _native.available()
    protos = []
    positions = packed.vertices['pos']
    for face, edge in zip(packed.commands, packed.edge_commands):
        start = int(face['base'])
        tris = positions[start:start + int(face['count'])].astype(np.float64).reshape(-1, 3, 3)
        start += int(face['count'])
        edges = positions[start:start + int(edge['count'])].astype(np.float64).reshape(-1, 6)
        protos.append(native.InstanceProto(
            np.ascontiguousarray(tris[:, 0]),
            np.ascontiguousarray(tris[:, 1] - tris[:, 0]),
            np.ascontiguousarray(tris[:, 2] - tris[:, 0]), edges))
    mats = packed.instances['world'].astype(np.float64).reshape(-1, 16)
    ids = packed.instances['info'][:, 0].astype(np.int64)
    bounds = packed.bounds[ids, :, :3].astype(np.float64)
    matrix = mats.reshape(-1, 4, 4).transpose(0, 2, 1)
    center = bounds.mean(axis=1)
    extent = (bounds[:, 1] - bounds[:, 0]) / 2
    wc = np.einsum('nij,nj->ni', matrix[:, :3, :3], center) + matrix[:, :3, 3]
    we = np.einsum('nij,nj->ni', abs(matrix[:, :3, :3]), extent)
    return native.InstanceSet(protos, ids, mats, np.ascontiguousarray(wc-we),
                              np.ascontiguousarray(wc+we))


def surface(index, row, origin, direction):
    """Use the GL picker's exact triangle test after the prototype BVH."""
    from views.viewport import _moller_trumbore
    rows = np.array([row], np.int64)
    _, _, v0, e1, e2 = index.ray_cands(rows, origin.toTuple(), direction.toTuple(), float('inf'))
    if not len(v0):
        return None
    t, hit = _moller_trumbore(np.array(origin.toTuple()), np.array(direction.toTuple()), v0, e1, e2)
    valid = t[hit]
    if not len(valid):
        return None
    return origin + direction * float(valid.min())


def snap(index, row, view, x, y, **options):
    origin, direction = view._pixel_to_ray(x, y)
    point = surface(index, row, origin, direction)
    on_face = point is not None
    if point is None:
        point = QVector3D(view.camera.target)
    mvp = view.camera.projection_matrix() * view.camera.view_matrix()
    _, _, a, b, _ = index.edges_near(np.array([row], np.int64), mvp.data(),
                                    float(view.width()), float(view.height()),
                                    float(x), float(y), 12., 256)
    edges = [SimpleNamespace(a=QVector3D(*aa), b=QVector3D(*bb), in_group=True,
                             context='group') for aa, bb in zip(a, b)]
    def occluded(candidate):
        pixel = view._world_to_pixel(candidate)
        if pixel is None:
            return True
        eye, ray = view._pixel_to_ray(*pixel)
        front = surface(index, row, eye, ray)
        return front is not None and (front-eye).length() + 1e-4 < (candidate-eye).length()

    return compute_snap(point, (x, y), SimpleNamespace(edges=edges),
                        view._world_to_pixel, 12., face_under_cursor=on_face, is_occluded=occluded, **options)
