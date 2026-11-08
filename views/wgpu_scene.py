"""Pack resident GPU arrays without creating faces for deferred geometry.

The ABI is little endian: 28-byte vertices, 32-byte prototype bounds,
80-byte instances and 20-byte indexed indirect commands. Alpha zero marks
unpainted faces so container tint never overwrites explicit face colour.
"""
from dataclasses import dataclass
from types import SimpleNamespace
import numpy as np
from core import _native
from core.geometry_arrays import arrays_of
from core.group import iter_placements
from core.lazy_mesh import plan_of
from views.array_bake import _attrs_table

VERTEX = np.dtype([('pos', '<f4', 3), ('normal', '<f4', 3), ('color', 'u1', 4)])
INSTANCE = np.dtype([('world', '<f4', (4, 4)), ('info', '<u4', 4)])
COMMAND = np.dtype([('count', '<u4'), ('instances', '<u4'), ('first', '<u4'),
                    ('base', '<i4'), ('start', '<u4')])


@dataclass
class PackedScene:
    vertices: np.ndarray
    indices: np.ndarray
    bounds: np.ndarray
    commands: np.ndarray
    edge_commands: np.ndarray
    instances: np.ndarray
    uids: list
    world_bounds: np.ndarray

    def upload(self, renderer):
        renderer.set_scene(tuple(a.view(np.uint8).reshape(-1) for a in
                                 (self.vertices, self.indices, self.bounds, np.concatenate((self.commands, self.edge_commands)))),
                           self.instances.view(np.uint8).reshape(-1))


def bake_mesh(mesh):
    """Reuse the array bake's kernel outputs, including hole triangulation."""
    plan = plan_of(mesh)
    if plan is not None:
        arrays = plan
        src = mesh.__dict__['_deferred_source']
        table = _attrs_table(src)
        attr = np.asarray(src['face_attr'], dtype=np.int64)
        pos = plan.pos
    else:
        arrays = arrays_of(mesh)
        pos = arrays.pos

        table = [f.attrs for f in mesh.faces]
        attr = np.arange(len(table))
    # Gather once through the attribute table; masking every face for each
    # distinct colour is quadratic on large, per-face-painted prototypes.
    palette = np.full((len(table)+1, 4), 255, np.uint8)
    palette[:, :3] = 210
    palette[:, 3] = 0
    hidden_table = np.zeros(len(table)+1, bool)
    for k, own in enumerate(table):
        hidden_table[k+1] = bool(own.get('hidden'))
        if own.get('color') is not None:
            palette[k+1, :3] = np.clip(np.array(own['color'][:3])*255, 0, 255)
            palette[k+1, 3] = 255
    colors = palette[attr+1]
    hidden = hidden_table[attr+1]
    native = _native.available()
    return native.bake_vertices(
        np.asarray(pos, np.float32), arrays.corners, arrays.ring_sizes,
        arrays.ring_counts, colors, hidden, _native.qt_hypot()).view(VERTEX)



def pack_scene(scene, view_tint=None):
    from views.viewport import _paint_of
    vp = SimpleNamespace(scene=scene)
    meshes, lookup, rows, uids, paints = [], {}, [], [], []
    local_bounds = []
    face_counts = []
    placements = [(None, None, scene.mesh, False)]
    for root in scene.groups:
        root_hidden = not scene.entity_visible(root)
        placements.extend((g, matrix, g.mesh, root_hidden or not scene.entity_visible(g))
                          for g, matrix in iter_placements(root))
    for group, matrix, mesh, hidden in placements:
        key = id(mesh)
        if key not in lookup:
            verts = bake_mesh(mesh)
            face_counts.append(len(verts))
            plan = plan_of(mesh)
            if plan is not None:
                raw, _bounds = _native.available().bake_edges(
                    np.asarray(plan.pos, np.float32), plan.edges,
                    plan.soft.astype(np.uint8) | (plan.hidden.astype(np.uint8) << 1))
                lines = raw.view(VERTEX)
            else:
                ep = np.asarray([v.position.toTuple() for e in mesh.edges
                                 if not e.soft and not e.hidden for v in (e.v0, e.v1)]).reshape(-1, 3)
                lines = np.zeros(len(ep), VERTEX)
                lines['pos'] = ep
                lines['normal'][:, 2] = 1
            verts = np.concatenate((verts, lines))
            positions = (plan.pos if plan is not None else
                         np.asarray([v.position.toTuple() for v in mesh.vertices]).reshape(-1, 3))
            if not len(positions):
                lookup[key] = -1
                face_counts.pop()
            else:
                lookup[key] = len(meshes)
                meshes.append(verts)
                local_bounds.append((positions.min(axis=0), positions.max(axis=0)))
        code = lookup[key]
        if code < 0:
            continue
        world = np.eye(4, dtype=np.float32) if matrix is None else np.array(matrix.data(), np.float32).reshape(4, 4)
        rows.append((code, world, hidden))
        uids.append(getattr(group, 'uid', 'loose'))
        paint = _paint_of(vp, group) or {}
        rgb = paint.get('color') or (210/255,)*3
        paints.append(np.array([*np.clip(np.array(rgb[:3])*255, 0, 255), 255], np.uint8).view('<u4')[0])
    bounds = np.zeros((len(meshes), 2, 4), '<f4')
    commands = np.zeros(len(meshes), COMMAND)
    edge_commands = np.zeros(len(meshes), COMMAND)
    instances = np.zeros(len(rows), INSTANCE)
    for i, (code, world, hidden) in enumerate(rows):
        instances['world'][i] = world
        tint = (view_tint or {}).get(uids[i])
        override = (np.array([*np.clip(np.array(tint[:3])*255, 0, 255), 255],
                             np.uint8).view('<u4')[0] if tint is not None else 0)
        instances['info'][i] = (code, paints[i], int(hidden), override)
    counts = np.bincount(instances['info'][:, 0], minlength=len(meshes))
    offset, start = 0, 0
    for i, vertices in enumerate(meshes):
        bounds[i, 0, :3] = local_bounds[i][0]
        bounds[i, 1, :3] = local_bounds[i][1]
        commands[i] = (face_counts[i], 0, offset, offset, start)
        edge_commands[i] = (len(vertices)-face_counts[i], 0, offset+face_counts[i], offset, start)
        offset += len(vertices)
        start += int(counts[i])
    indices = np.concatenate([np.arange(len(v), dtype='<u4') for v in meshes]) if meshes else np.empty(0, '<u4')
    vertices = np.concatenate(meshes) if meshes else np.empty(0, VERTEX)
    world_bounds = np.zeros((2, 3))
    if len(rows):
        shown = instances[instances['info'][:, 2] == 0]
        if not len(shown):
            return PackedScene(vertices, indices, bounds, commands, edge_commands, instances, uids, world_bounds)
        b = bounds[shown['info'][:, 0], :, :3]
        center, extent = (b[:, 0]+b[:, 1])/2, (b[:, 1]-b[:, 0])/2
        mat = shown['world'].transpose(0, 2, 1)
        wc = np.einsum('nij,nj->ni', mat[:, :3, :3], center)+mat[:, :3, 3]
        we = np.einsum('nij,nj->ni', abs(mat[:, :3, :3]), extent)
        world_bounds = np.array([(wc-we).min(axis=0), (wc+we).max(axis=0)])
    return PackedScene(vertices, indices, bounds, commands, edge_commands, instances, uids, world_bounds)
