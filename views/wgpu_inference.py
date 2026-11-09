"""Reuse exact snap rules with resident prototype candidates, never a GL bake.

Initial preparation owns immutable packed arrays and runs away from Qt. Edits
reuse unchanged prototype BVHs and create local placement sets only when queried.
"""
from types import SimpleNamespace
import numpy as np
from PySide6.QtGui import QVector3D
from core import _native
from core.snap import compute_snap


def _prototype(packed, code):
    face, edge = packed.commands[code], packed.edge_commands[code]
    positions = packed.vertices['pos']
    start = int(face['base'])
    tris = positions[start:start + int(face['count'])].astype(np.float64).reshape(-1, 3, 3)
    start += int(face['count'])
    edges = positions[start:start + int(edge['count'])].astype(np.float64).reshape(-1, 6)
    return _native.available().InstanceProto(
        np.ascontiguousarray(tris[:, 0]),
        np.ascontiguousarray(tris[:, 1] - tris[:, 0]),
        np.ascontiguousarray(tris[:, 2] - tris[:, 0]), edges)


class ResidentInference:
    """Keep immutable prototype BVHs; edited IDs get a tiny local placement set.

    Native hover queries always name one picked row. Retaining the original
    set avoids both rebuilding and destroying a document-sized BVH on input.
    Only queried edited rows construct a replacement placement acceleration.
    """
    def __init__(self, base, protos, packed):
        self.base = base
        self.protos = protos
        self.initial = packed.instances.copy()
        self.bounds = [bound.copy() for bound in packed.bounds]
        self.rows = {}
        self.changed = set()
        self.local = {}

    def update(self, ids, packed, changed_codes=()):
        for code in changed_codes:
            while len(self.protos) <= code:
                self.protos.append(None)
                self.bounds.append(None)
            self.protos[code] = _prototype(packed, code)
            self.bounds[code] = packed.bounds[code].copy()
            self.changed.add(code)
            for row, (cached_code, _) in list(self.local.items()):
                if cached_code == code:
                    del self.local[row]
        for row in ids:
            row = int(row)
            self.rows[row] = packed.instances[row].copy()
            self.local.pop(row, None)

    def _query(self, name, rows, *args):
        if len(rows) != 1:
            raise ValueError('resident inference requires one picked row')
        row = int(rows[0])
        value = self.rows.get(row)
        if value is None:
            value = self.initial[row]
        code = int(value['info'][0])
        if row not in self.rows and code not in self.changed:
            return getattr(self.base, name)(rows, *args)
        if row not in self.local:
            matrix = value['world'].astype(np.float64).T
            bounds = self.bounds[code][:, :3].astype(np.float64)
            center, extent = bounds.mean(axis=0), (bounds[1]-bounds[0])*.5
            wc = matrix[:3, :3] @ center + matrix[:3, 3]
            we = abs(matrix[:3, :3]) @ extent
            index = _native.available().InstanceSet(
                [self.protos[code]], np.array([0], np.int64),
                value['world'].astype(np.float64).reshape(1, 16),
                np.ascontiguousarray((wc-we).reshape(1, 3)),
                np.ascontiguousarray((wc+we).reshape(1, 3)))
            self.local[row] = (code, index)
        return getattr(self.local[row][1], name)(np.array([0], np.int64), *args)

    def ray_cands(self, rows, *args):
        return self._query('ray_cands', rows, *args)

    def edges_near(self, rows, *args):
        return self._query('edges_near', rows, *args)


def prepare(packed):
    native = _native.available()
    protos = [_prototype(packed, code) for code in range(len(packed.commands))]
    mats = packed.instances['world'].astype(np.float64).reshape(-1, 16)
    ids = packed.instances['info'][:, 0].astype(np.int64)
    bounds = packed.bounds[ids, :, :3].astype(np.float64)
    matrix = mats.reshape(-1, 4, 4).transpose(0, 2, 1)
    center = bounds.mean(axis=1)
    extent = (bounds[:, 1] - bounds[:, 0]) / 2
    wc = np.einsum('nij,nj->ni', matrix[:, :3, :3], center) + matrix[:, :3, 3]
    we = np.einsum('nij,nj->ni', abs(matrix[:, :3, :3]), extent)
    base = native.InstanceSet(protos, ids, mats, np.ascontiguousarray(wc-we),
                              np.ascontiguousarray(wc+we))
    return ResidentInference(base, protos, packed)


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
    group, _ = view.resolve(row)
    loose = ((group is None and view.scene.edit_group is None)
             or group is view.scene.edit_group)
    edges = [SimpleNamespace(a=QVector3D(*aa), b=QVector3D(*bb), in_group=not loose,
                             context=None if loose else 'group') for aa, bb in zip(a, b)]
    tool = getattr(getattr(view, 'tools', None), 'tool', None)
    moving = getattr(tool, '_verts', ()) if getattr(tool, 'grab', None) is not None else ()
    if loose and moving and not getattr(tool, '_copy', False):
        from core.topology import _key
        excluded = {_key(v.position) for v in moving}
        edges = [e for e in edges if _key(e.a) not in excluded and _key(e.b) not in excluded]
        point = view.tools.work_point(x, y) or point
        on_face = False
    if group is not None and group.is_instance():
        origin = QVector3D(*view.packed.instances['world'][row, 3, :3])
        edges.insert(0, SimpleNamespace(a=origin, b=origin, component_origin=True))

    def occluded(candidate):
        pixel = view._world_to_pixel(candidate)
        if pixel is None:
            return True
        eye, ray = view._pixel_to_ray(*pixel)
        front = surface(index, row, eye, ray)
        return front is not None and (front-eye).length() + 1e-4 < (candidate-eye).length()

    return compute_snap(point, (x, y), SimpleNamespace(edges=edges),
                        view._world_to_pixel, 12., face_under_cursor=on_face, is_occluded=occluded, **options)
