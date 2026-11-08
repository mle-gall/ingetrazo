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
    timings: dict | None = None
    groups: list | None = None

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



def _source_arrays(mesh):
    """Use source topology directly; the resident renderer needs no welded Plan."""
    src = mesh.__dict__.get('_deferred_source')
    if src is not None:
        pos, corners, sizes, counts = (src[k] for k in ('pos', 'rings', 'sizes', 'counts'))
        edges = src['edges']
        flags = src['flags']
        if flags is None:
            flags = np.zeros(len(edges), np.uint8)
        table = src['meta'].get('face_attrs') or []
        attr = np.asarray(src['face_attr'], np.int64)
    else:
        arrays = arrays_of(mesh)
        # arrays_of stores face vertices only. Append legacy edge endpoints and
        # unused vertices so edge-only prototypes retain their original bounds.
        extra = np.asarray([v.position.toTuple() for v in mesh.vertices], np.float32).reshape(-1, 3)
        lookup = {id(v): i+len(arrays.pos) for i, v in enumerate(mesh.vertices)}
        pos = np.concatenate((arrays.pos, extra))
        corners, sizes, counts = arrays.corners, arrays.ring_sizes, arrays.ring_counts
        edges = np.asarray([(lookup[id(e.v0)], lookup[id(e.v1)]) for e in mesh.edges], np.int64).reshape(-1, 2)
        # Face corners and edges must share indices for boundary deduplication.
        positions = {tuple(p): i for i, p in enumerate(pos.tolist())}
        remap = np.fromiter((positions[tuple(p)] for p in arrays.pos.tolist()),
                            dtype=np.int64, count=len(arrays.pos))
        corners = remap[corners]
        flags = np.asarray([int(e.soft) | (int(e.hidden) << 1) for e in mesh.edges], np.uint8)
        table = [f.attrs for f in mesh.faces]
        attr = np.arange(len(table))
    palette = np.full((len(table)+1, 4), 210, np.uint8)
    palette[:, 3] = 0
    hidden = np.zeros(len(table)+1, bool)
    hidden[1:] = [bool(own.get('hidden')) for own in table]
    painted = [(k+1, own['color'][:3]) for k, own in enumerate(table)
               if own.get('color') is not None]
    if painted:
        ids, rgb = zip(*painted)
        ids = np.asarray(ids, np.int64)
        palette[ids, :3] = np.clip(np.asarray(rgb)*255, 0, 255)
        palette[ids, 3] = 255
    return (np.asarray(pos, np.float32), np.asarray(corners, np.int64),
            np.asarray(sizes, np.int64), np.asarray(counts, np.int64),
            np.asarray(edges, np.int64), np.asarray(flags, np.uint8),
            palette, hidden[attr+1], attr+1)


def _placement_state(scene):
    """Memoise layer/material work while preserving edit and navigator filters."""
    from core.group import effective_material
    from core.layers import object_layer
    from core.materials import material_sig
    from views.viewport import _paint_of
    vp = SimpleNamespace(scene=scene)
    visibility, paints = {}, {}

    def state(group):
        if group is None:
            visible = True
        elif scene._edit_stack or getattr(scene, '_navigator_allowed', None) is not None:
            visible = scene.entity_visible(group)
        else:
            key = (group.layer, bool(group.hidden))
            if key not in visibility:
                visibility[key] = scene.entity_visible(group)
            visible = visibility[key]
        material = effective_material(group)
        key = (object_layer(group), material_sig(material))
        if key not in paints:
            paint = _paint_of(vp, group) or {}
            rgb = paint.get('color') or (210/255,)*3
            paints[key] = np.array([*np.clip(np.array(rgb[:3])*255, 0, 255), 255], np.uint8).view('<u4')[0]
        return visible, paints[key]
    return state


def pack_scene(scene, view_tint=None):
    from time import perf_counter
    try:
        import resource
    except ImportError:
        resource = None
    begin = perf_counter()
    state = _placement_state(scene)
    meshes, lookup, rows, uids, paints = [], {}, [], [], []
    groups = []
    placements = [(None, None, scene.loose_mesh, False)]
    # Visibility is inherited down the tree, as the GL proxies do it: a
    # placement inside a hidden group, or inside a group whose tag is off,
    # is hidden whatever its own flags say. Taking only the root's state
    # drew the ride's hidden concrete volumes and context walls (R-look).
    parent_of = {}

    def map_parents(group):
        for child in getattr(group, 'children', None) or ():
            parent_of[id(child)] = group
            map_parents(child)
    hidden_of = {}
    for root in scene.groups:
        map_parents(root)
        for g, matrix in iter_placements(root):
            parent = parent_of.get(id(g))
            inherited = hidden_of.get(id(parent), False) if parent is not None else False
            hidden_of[id(g)] = inherited or not state(g)[0]
            placements.append((g, matrix, g.mesh, hidden_of[id(g)]))
    for group, matrix, mesh, hidden in placements:
        key = id(mesh)
        if key not in lookup:
            arrays = _source_arrays(mesh)
            lookup[key] = len(meshes) if len(arrays[0]) else -1
            if len(arrays[0]):
                meshes.append(arrays)
        code = lookup[key]
        if code < 0:
            continue
        visible, paint = state(group)
        world = np.eye(4, dtype=np.float32) if matrix is None else np.array(matrix.data(), np.float32).reshape(4, 4)
        rows.append((code, world, hidden or not visible))
        uids.append(getattr(group, 'uid', 'loose'))
        groups.append(group)
        paints.append(paint)
    offsets = np.zeros((len(meshes)+1, 5), np.int64)
    for i, arrays in enumerate(meshes):
        offsets[i+1] = [len(a) for a in arrays[:5]]
    np.cumsum(offsets, axis=0, out=offsets)
    empty = (np.empty((0,3), np.float32), np.empty(0, np.int64),
             np.empty(0, np.int64), np.empty(0, np.int64),
             np.empty((0,2), np.int64), np.empty(0, np.uint8),
             np.empty((0,4), np.uint8), np.empty(0, bool), np.empty(0, np.int64))
    palette_offsets = np.cumsum([0]+[len(m[6]) for m in meshes])
    attributes = (np.concatenate([m[8]+offset for m, offset in zip(meshes, palette_offsets)])
                  if meshes else empty[8])
    arrays = [np.concatenate([m[k] for m in meshes]) if meshes else empty[k] for k in range(8)]
    handoff = perf_counter()
    raw, indices, bounds, table = _native.available().bake_scene(
        *arrays[:4], arrays[6], arrays[7], arrays[4], arrays[5], offsets, attributes, _native.qt_hypot())
    baked = perf_counter()
    vertices = raw.view(VERTEX)
    bounds = bounds.reshape(-1, 2, 4)
    table = table.reshape(-1, 3)
    commands = np.zeros(len(meshes), COMMAND)
    edge_commands = np.zeros(len(meshes), COMMAND)
    instances = np.zeros(len(rows), INSTANCE)
    if rows:
        instances['world'] = [r[1] for r in rows]
        instances['info'][:, 0] = [r[0] for r in rows]
        instances['info'][:, 1] = paints
        instances['info'][:, 2] = [r[2] for r in rows]
        for i, uid in enumerate(uids):
            tint = (view_tint or {}).get(uid)
            if tint is not None:
                instances['info'][i, 3] = np.array([*np.clip(np.array(tint[:3])*255, 0, 255), 255], np.uint8).view('<u4')[0]
    counts = np.bincount(instances['info'][:, 0], minlength=len(meshes))
    commands['count'] = table[:, 1]
    edge_commands['count'] = table[:, 2]
    commands['first'] = commands['base'] = edge_commands['base'] = table[:, 0]
    edge_commands['first'] = table[:, 0]+table[:, 1]
    commands['start'] = edge_commands['start'] = np.cumsum(counts)-counts
    world_bounds = np.zeros((2, 3))
    if len(rows):
        shown = instances[instances['info'][:, 2] == 0]
        if not len(shown):
            return PackedScene(vertices, indices, bounds, commands, edge_commands, instances, uids, world_bounds, dict(handoff=handoff-begin, native=baked-handoff, finish=perf_counter()-baked, peak_build_rss_bytes=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None)), groups)
        b = bounds[shown['info'][:, 0], :, :3]
        center, extent = (b[:, 0]+b[:, 1])/2, (b[:, 1]-b[:, 0])/2
        mat = shown['world'].transpose(0, 2, 1)
        wc = np.einsum('nij,nj->ni', mat[:, :3, :3], center)+mat[:, :3, 3]
        we = np.einsum('nij,nj->ni', abs(mat[:, :3, :3]), extent)
        world_bounds = np.array([(wc-we).min(axis=0), (wc+we).max(axis=0)])
    return PackedScene(vertices, indices, bounds, commands, edge_commands, instances, uids, world_bounds, dict(handoff=handoff-begin, native=baked-handoff, finish=perf_counter()-baked, peak_build_rss_bytes=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None)), groups)
