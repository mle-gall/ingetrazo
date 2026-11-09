"""Resident inference API for P1 (no GL bake or viewport construction).

``prepare(packed, scene=None) -> ResidentInference`` runs in the existing
background preparation job. Pass scene to retain loose hidden/soft edges;
packed.groups supplies placement meshes. Reprepare on hidden-geometry/layer
policy changes, as for the render pack. ``update(ids, packed, changed_codes=())``
retains unchanged BVHs; call after placement, geometry and flag changes, including
billboards and edit-rest flags (64 = rest, 128 = hidden rest). No document-sized BVH rebuild on hover.

``nearby_edges(index, packed, camera, width, height, x, y, *, radius_px=48,
cap=48, rows=None, edit_group=None)`` returns nearest world-space pseudo edges
(a, b, row, edge_id, distance, group, in_group, context). Use uid_rows to supply
an optional row subset; use group/edit_group to split loose/group facade calls.
These are inference records, NOT editable topology Edges. edge_id is the filtered
prototype edge ordinal, not a mesh edge ID. Resolve topology before editing.
``reference_edge(index, view, x, y, radius_px=None)`` returns one visible pseudo
edge or None for Tape/Protractor/Rotate. ``tangent_direction(index, packed, row,
point)`` returns a world unit direction at a curve endpoint or None.
``scene_edges(view)`` returns guide/point/image-border pseudo edges (source is
the original record). Image records implement border_edges() and locked; scene
supplies entity_selectable(). ``snap(index, row, view, x, y, **options)`` returns
GL's SnapResult, even with row=None. All compute_snap lock/reference/acquisition
keywords pass through; view supplies scene, packed, camera, width/height,
_pixel_to_ray, _world_to_pixel and optionally tools.work_point/tool and GL pixel
tolerances. P1 must call snap without a picked face too. ``surface(index, row,
origin, direction)`` also accepts row arrays and returns a world point or None.

Kinds/priorities are owned by core.snap (endpoint, midpoint, on_edge, on_face,
intersection, center, parallel, perpendicular, reference, axis, from_point,
etc.). Arc tools consume tangent_direction to produce their tangent preview;
tangent is not a new competing compute_snap rule. Defaults retain the previous
12 px snap tolerance when the GL thresholds are not supplied by the facade.
"""
from collections.abc import Sequence
from types import SimpleNamespace
import numpy as np
from PySide6.QtGui import QVector3D
from core import _native
from core.snap import compute_snap


def _source_visible(source, scene):
    layers = source.get('layers')
    visible = getattr(scene, 'entity_visible', None)
    names = source.get('meta', {}).get('edge_layers') or ()
    if layers is None or visible is None or not names:
        return np.ones(len(source['edges']), bool)
    # The negative sentinel (untagged) always passes. Evaluate layer policy
    # once per name and gather the mask in a single pass over edges.
    allowed = np.array([visible(SimpleNamespace(layer=name)) for name in names] + [True])
    return allowed[np.where(layers >= 0, layers, -1)]


def _prototype(packed, code, scene, first_row):
    face, edge = packed.commands[code], packed.edge_commands[code]
    positions = packed.vertices['pos']
    start = int(face['base'])
    tris = positions[start:start + int(face['count'])].reshape(-1, 3, 3)
    start += int(face['count'])
    groups = getattr(packed, 'groups', None)
    group = groups[first_row] if groups is not None and first_row >= 0 else None
    mesh = group.mesh if group is not None else getattr(scene, 'loose_mesh', None)
    curves = []
    if mesh is None:
        edges = positions[start:start + int(edge['count'])].astype(np.float64).reshape(-1, 6)
    else:
        reveal = bool(getattr(scene, 'show_hidden_geometry', False))
        source = mesh.__dict__.get('_deferred_source')
        if source is not None:
            keep = _source_visible(source, scene)
            flags = source['flags']
            if flags is not None and not reveal:
                keep &= (flags & (3 if group is not None else 2)) == 0
            edges = source['pos'][source['edges'][keep]].reshape(-1, 6)
            ids = source.get('curves')
            if ids is not None:
                ids = ids[keep]
                selected = np.flatnonzero(ids >= 0)
                if len(selected):
                    # Stable within a curve, and retain first-seen curve
                    # order because equally close snap candidates can tie.
                    _, first, inverse = np.unique(ids[selected], return_index=True,
                                                  return_inverse=True)
                    order = np.argsort(inverse, kind='stable')
                    ends = np.cumsum(np.bincount(inverse))[:-1]
                    segments = np.split(edges[selected[order]], ends)
                    curves = [segments[i] for i in np.argsort(first)]
        else:
            visible = getattr(scene, 'edge_snappable', lambda e: not e.hidden or reveal)
            lines, named = [], {}
            for e in mesh.edges:
                if visible(e) and (group is None or reveal or not e.soft):
                    pair = (e.a.toTuple(), e.b.toTuple())
                    lines.append(pair)
                    if e.curve is not None:
                        named.setdefault(e.curve, []).append(pair)
            edges = np.asarray(lines, float).reshape(-1, 6)
            curves = named.values()
    tris = tris.astype(np.float64)
    proto = _native.available().InstanceProto(
        np.ascontiguousarray(tris[:, 0]),
        np.ascontiguousarray(tris[:, 1] - tris[:, 0]),
        np.ascontiguousarray(tris[:, 2] - tris[:, 0]), np.asarray(edges, float))
    return proto, curves


def _curve_features(curves):
    """Fit only a queried prototype's named curves from its visibility snapshot."""
    from core.snap import fit_circle
    centers, tangents = [], []
    for segments in curves:
        ends = np.asarray(segments, float).reshape(-1, 3)
        points, counts = np.unique(ends, axis=0, return_counts=True)
        fit = fit_circle([QVector3D(*p) for p in points]) if len(points) >= 3 else None
        if fit is None:
            continue
        center = np.array(fit[0].toTuple())
        centers.append(center)
        for point in points[counts == 1]:
            at = np.flatnonzero(np.all(ends == point, axis=1))[0]
            leaving = point - ends[at ^ 1]
            radial = point-center
            radial /= np.linalg.norm(radial)
            tangent = leaving-radial*np.dot(leaving, radial)
            length = np.linalg.norm(tangent)
            if length > 1e-9:
                tangents.append((point, tangent/length))
    return centers, tangents


def tangent_direction(index, packed, row, point):
    if row not in eligible_rows(index, packed):
        return None
    value = index.rows.get(row, packed.instances[row])
    matrix = value['world'].astype(float).T
    for endpoint, tangent in index.features[int(value['info'][0])][1]:
        world = matrix[:3, :3] @ endpoint + matrix[:3, 3]
        if (point-QVector3D(*world)).length() <= 1e-6:
            direction = QVector3D(*(matrix[:3, :3] @ tangent))
            if direction.length() > 1e-9:
                return direction.normalized()
    return None


class _CurveFeatures(Sequence):
    """Prototype-indexed curve fits; discard the input segments once fitted."""

    def __init__(self, curves):
        self.pending = curves
        self.fitted = [None] * len(curves)

    def __len__(self):
        return len(self.fitted)

    def __getitem__(self, code):
        if isinstance(code, slice):
            return [self[i] for i in range(*code.indices(len(self)))]
        if self.fitted[code] is None:
            self.fitted[code] = _curve_features(self.pending[code])
            self.pending[code] = None
        return self.fitted[code]

    def replace(self, code, curves):
        while len(self) <= code:
            self.pending.append(())
            self.fitted.append(None)
        self.pending[code] = curves
        self.fitted[code] = None


class ResidentInference:
    """Keep immutable prototype BVHs; edited IDs get a tiny local placement set.

    Queries merge the original placement set with edited local sets. Retaining it
    set avoids both rebuilding and destroying a document-sized BVH on input.
    Only queried edited rows construct a replacement placement acceleration.
    """
    def __init__(self, base, protos, curves, packed, scene=None):
        self.packed = packed
        self.scene = scene
        self.features = _CurveFeatures(curves)
        self.context_rows = {}
        self.screen_cache = None
        self.screen_dirty = set()
        self.epoch = 0
        self.base = base
        self.protos = protos
        self.initial = packed.instances.copy()
        self.bounds = [bound.copy() for bound in packed.bounds]
        self.rows = {}
        self.changed = set()
        self.local = {}
        self.replaced = np.zeros(len(packed.instances), bool)

    def update(self, ids, packed, changed_codes=()):
        self.epoch += 1
        self.packed = packed
        if len(self.replaced) < len(packed.instances):
            self.context_rows.clear()
            self.replaced = np.pad(self.replaced, (0, len(packed.instances)-len(self.replaced)))
        for code in changed_codes:
            while len(self.protos) <= code:
                self.protos.append(None)
                self.bounds.append(None)

            affected = np.flatnonzero(packed.instances['info'][:, 0] == code)
            self.protos[code], curves = _prototype(
                packed, code, self.scene, affected[0] if len(affected) else -1)
            self.bounds[code] = packed.bounds[code].copy()
            self.features.replace(code, curves)
            self.changed.add(code)
            self.replaced[affected] = True
            self.screen_dirty.update(affected.tolist())
            for row, (cached_code, _) in list(self.local.items()):
                if cached_code == code:
                    del self.local[row]
        for row in ids:
            row = int(row)
            self.rows[row] = packed.instances[row].copy()
            self.local.pop(row, None)
            self.replaced[row] = True
            self.screen_dirty.add(row)

    def _query(self, name, rows, *args):
        rows = np.asarray(rows, np.int64)
        if not self.rows and not self.changed:
            return getattr(self.base, name)(rows, *args)
        if len(rows) != 1:
            edited = self.replaced[rows]
            parts = [getattr(self.base, name)(rows[~edited], *args)]
            for row in rows[edited]:
                parts.append(self._query(name, np.array([row], np.int64), *args))
            merged = tuple(np.concatenate([part[k] for part in parts]) for k in range(5))
            if name == 'edges_near':
                order = np.lexsort((merged[1], merged[0], merged[4]))[:args[-1]]
                merged = tuple(a[order] for a in merged)
            return merged
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
        result = getattr(self.local[row][1], name)(np.array([0], np.int64), *args)
        return (np.full(len(result[0]), row, np.int64), *result[1:])

    def ray_cands(self, rows, *args):
        return self._query('ray_cands', rows, *args)

    def edges_near(self, rows, *args):
        return self._query('edges_near', rows, *args)


def prepare(packed, scene=None):
    native = _native.available()
    codes, rows = np.unique(packed.instances['info'][:, 0], return_index=True)
    first = np.full(len(packed.commands), -1, dtype=np.int64)
    first[codes] = rows
    protos, curves = [], []
    for code, row in enumerate(first):
        proto, named = _prototype(packed, code, scene, row)
        protos.append(proto)
        curves.append(named)
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
    return ResidentInference(base, protos, curves, packed, scene)


def surface(index, row, origin, direction, limit=float('inf')):
    """Use the GL picker's exact triangle test after the prototype BVH."""
    from views.viewport import _moller_trumbore
    rows = np.asarray(row, np.int64).reshape(-1)
    rows = rows[(rows >= 0) & (rows < len(index.packed.instances))]
    rows = rows[(index.packed.instances['info'][rows, 2] & 129) == 0]
    _, _, v0, e1, e2 = index.ray_cands(rows, origin.toTuple(), direction.toTuple(), limit)
    if not len(v0):
        return None
    t, hit = _moller_trumbore(np.array(origin.toTuple()), np.array(direction.toTuple()), v0, e1, e2)
    valid = t[hit]
    if not len(valid):
        return None
    return origin + direction * float(valid.min())


def eligible_rows(index, packed=None):
    """Visible placements, including overrides from incremental/billboard updates."""
    values = (index.packed if packed is None else packed).instances
    flags = values['info'][:, 2]
    return np.flatnonzero((flags & (1 | 128)) == 0).astype(np.int64)


def screen_boxes(index, packed, mvp, width, height):
    """Cached conservative screen boxes; only moved rows reproject after edits."""
    key = (tuple(mvp.data()), width, height, len(packed.instances))
    cache = index.screen_cache
    if cache is None or cache[0] != key:
        lo = np.empty((len(packed.instances), 2))
        hi = np.empty_like(lo)
        changed = np.arange(len(lo))
        grid, moved = None, set()
    else:
        _, lo, hi, grid, moved = cache
        changed = np.fromiter(index.screen_dirty, np.int64)
    if len(changed):
        values = packed.instances[changed]
        matrices = values['world'].astype(float).transpose(0, 2, 1)
        bounds = packed.bounds[values['info'][:, 0], :, :3].astype(float)
        center = bounds.mean(axis=1)
        extent = (bounds[:, 1]-bounds[:, 0])*.5
        wc = np.einsum('nij,nj->ni', matrices[:, :3, :3], center)+matrices[:, :3, 3]
        we = np.einsum('nij,nj->ni', abs(matrices[:, :3, :3]), extent)
        signs = np.array([[a,b,c] for a in (-1,1) for b in (-1,1) for c in (-1,1)])
        corners = wc[:, None, :]+we[:, None, :]*signs
        matrix = np.asarray(mvp.data()).reshape(4, 4).T
        clip = corners @ matrix[:, :3].T + matrix[:, 3]
        front = clip[:, :, 3] > 1e-3
        denom = np.where(front, clip[:, :, 3], 1.)
        xy = clip[:, :, :2]/denom[:, :, None]
        xy = (xy*np.array([1., -1.])+1.)*np.array([width/2, height/2])
        low, high = xy.min(axis=1), xy.max(axis=1)
        crossing = front.any(axis=1) & ~front.all(axis=1)
        low[crossing], high[crossing] = -np.inf, np.inf
        low[~front.any(axis=1)], high[~front.any(axis=1)] = np.inf, np.inf
        lo[changed], hi[changed] = low, high
        index.screen_dirty.clear()
        if grid is None:
            from core.edge_grid import EdgeGrid
            # Cross-eye boxes must remain conservative; a full-screen box is
            # equivalent for cursors inside this view.
            low = np.where(np.isneginf(lo), -128., lo)
            high = np.where(np.isposinf(hi) & np.isfinite(low),
                            np.array([width+128., height+128.]), hi)
            grid = EdgeGrid(low[:, 0], low[:, 1], high[:, 0], high[:, 1],
                            np.isfinite(low).all(axis=1), width, height, 128.)
        else:
            moved.update(changed.tolist())
        index.screen_cache = (key, lo, hi, grid, moved)
    return lo, hi, grid, moved


def _screen_rows(index, packed, mvp, width, height, x, y, radius, rows):
    lo, hi, grid, moved = screen_boxes(index, packed, mvp, width, height)
    candidates = grid.near(x, y, radius) if grid is not None and radius <= 128 else None
    if candidates is not None:
        if moved:
            candidates = np.union1d(candidates, np.fromiter(moved, np.int64))
        mask = np.zeros(len(lo), bool)
        mask[rows] = True
        rows = candidates[mask[candidates]]
    gap = np.maximum(np.maximum(lo[rows]-[x,y], [x,y]-hi[rows]), 0.)
    return rows[np.einsum('ij,ij->i', gap, gap) < radius*radius]


def context_hit(view, context, x, y):
    from views.viewport import _moller_trumbore
    index = view.inference_index
    rows = np.asarray(view._rows_for_group(context), np.int64)
    flags = view.packed.instances['info'][rows, 2]
    rows = rows[(flags & 129) == 0]
    camera = view.camera
    mvp = camera.projection_matrix() * camera.view_matrix()
    radius = getattr(view.tools, "pick_threshold_px", 8.)
    rows = _screen_rows(index, view.packed, mvp, view.width(), view.height(), x, y, radius, rows)
    origin, direction = view._pixel_to_ray(x, y)
    placements, _, v0, e1, e2 = index.ray_cands(
        rows, origin.toTuple(), direction.toTuple(), float('inf'))
    if len(v0):
        t, hit = _moller_trumbore(np.array(origin.toTuple()), np.array(direction.toTuple()), v0, e1, e2)
        if np.any(hit):
            return int(placements[np.argmin(np.where(hit, t, np.inf))])
    placements, *_ = index.edges_near(rows, mvp.data(), float(view.width()),
        float(view.height()), float(x), float(y), float(radius), 1)
    return int(placements[0]) if len(placements) else None


def nearby_edges(index, packed, camera, width, height, x, y, *,
                 radius_px=48., cap=48, rows=None, edit_group=None):
    """World-space pseudo edges, nearest first; row/edge_id identify source."""
    if cap <= 0:
        return []
    if rows is None:
        rows = eligible_rows(index, packed)
    else:
        rows = np.asarray(rows, np.int64)
        rows = rows[(rows >= 0) & (rows < len(packed.instances))]
        rows = rows[(packed.instances['info'][rows, 2] & 129) == 0]
    mvp = camera.projection_matrix() * camera.view_matrix()
    rows = _screen_rows(index, packed, mvp, width, height, x, y, radius_px, rows)
    pl, ids, a, b, distances = index.edges_near(
        rows, mvp.data(), float(width), float(height), float(x), float(y),
        float(radius_px), int(cap))
    groups = getattr(packed, 'groups', None)
    result = []
    for row, eid, aa, bb, distance in zip(pl, ids, a, b, distances):
        group = groups[int(row)] if groups is not None else None
        loose = group is edit_group
        context = None if loose else ('component' if group is not None and group.is_instance() else 'group')
        result.append(SimpleNamespace(a=QVector3D(*aa), b=QVector3D(*bb),
            row=int(row), edge_id=int(eid), distance=float(distance), group=group,
            in_group=not loose, context=context))
    return result


def scene_edges(view):
    """Guides, guide points and selectable image borders using GL clipping."""
    from views.viewport import Viewport, shown_guides
    result = []
    tool = getattr(getattr(view, 'tools', None), 'tool', None)
    moving = getattr(tool, 'moving_guide_ids', lambda: ())()
    for guide in shown_guides(view.scene):
        if id(guide) in moving:
            continue
        segment = (Viewport._guide_snap_segment(view, guide) if guide.is_line else
                   (QVector3D(guide.point), QVector3D(guide.point)))
        if segment is not None:
            result.append(SimpleNamespace(a=segment[0], b=segment[1],
                                          guide=guide.is_line, source=guide))
    selectable = getattr(view.scene, 'entity_selectable', lambda e: True)
    for plane in getattr(view.scene, 'image_planes', ()) or ():
        if getattr(plane, 'locked', False) or not selectable(plane):
            continue
        for a, b in plane.border_edges():
            segment = Viewport._clip_segment_front(view, a, b)
            if segment is not None:
                result.append(SimpleNamespace(a=segment[0], b=segment[1], source=plane))
    return result


def reference_edge(index, view, x, y, radius_px=None):
    """Nearest visible world edge for Tape/Protractor/Rotate and arc tangency."""
    radius = radius_px if radius_px is not None else getattr(view, 'pick_threshold_px', 8.)
    edges = nearby_edges(index, view.packed, view.camera, view.width(), view.height(),
                         x, y, radius_px=radius, cap=48,
                         edit_group=view.scene.edit_group)
    from views.viewport import Viewport
    for edge in edges:
        pa, pb = view._world_to_pixel(edge.a), view._world_to_pixel(edge.b)
        if pa is None or pb is None:
            continue
        delta = edge.b-edge.a
        projected = Viewport._project_to_lock_line(view, edge.a, delta, x, y)
        t = (QVector3D.dotProduct(projected-edge.a, delta)/delta.lengthSquared()
             if delta.lengthSquared() > 1e-12 else 0.)
        point = edge.a + delta*max(0., min(1., t))
        if not _occluded(index, view, point):
            return edge
    return None


def _occluded(index, view, candidate, rows=None):
    pixel = view._world_to_pixel(candidate)
    if pixel is None:
        return True
    eye, ray = view._pixel_to_ray(*pixel)
    if eye is None or ray is None:
        return True
    if rows is None:
        rows = eligible_rows(index, view.packed)
    reach = (candidate-eye).length() - 1e-4
    fixed = rows[~index.replaced[rows]]
    hidden, doubt = index.base.occluded(fixed, eye.toTuple(),
        np.array([ray.toTuple()], float), np.array([reach], float))
    if hidden[0] and not doubt[0]:
        return True
    check = rows if doubt[0] else rows[index.replaced[rows]]
    if not len(check):
        return False
    front = surface(index, check, eye, ray, reach)
    return front is not None and (front-eye).length() < reach



def _occluded_many(index, view, points, rows=None):
    if not points:
        return []
    if rows is None:
        rows = eligible_rows(index, view.packed)
    if not getattr(view.camera, 'perspective', False) or index.replaced.any():
        return [_occluded(index, view, p, rows) for p in points]
    eye = view.camera.eye()
    delta = np.array([p.toTuple() for p in points], float)-eye.toTuple()
    lengths = np.linalg.norm(delta, axis=1)
    directions = delta/np.maximum(lengths[:, None], 1e-30)
    hidden, doubt = index.base.occluded(rows, eye.toTuple(),
        np.ascontiguousarray(directions), np.maximum(lengths-1e-4, 0.))
    result = hidden.tolist()
    for i in np.flatnonzero(doubt):
        result[i] = _occluded(index, view, points[i], rows)
    return result


def snap(index, row, view, x, y, **options):
    """GL SnapResult; row may be None (guides/edges do not need a face ID)."""
    if index is None:
        return None
    rows = eligible_rows(index, view.packed)
    origin, direction = view._pixel_to_ray(x, y)
    if origin is None or direction is None:
        return None
    point = surface(index, row, origin, direction) if row in rows else None
    on_face = point is not None
    tool = getattr(getattr(view, 'tools', None), 'tool', None)
    if point is None:
        work = getattr(getattr(view, 'tools', None), 'work_point', lambda x, y: None)
        point = work(x, y) if tool is not None else None
        if point is None:
            normal = getattr(view.camera, 'forward', lambda: direction)()
            denominator = QVector3D.dotProduct(direction, normal)
            point = (origin + direction * (QVector3D.dotProduct(
                view.camera.target-origin, normal)/denominator)
                if abs(denominator) > 1e-9 else QVector3D(view.camera.target))
    context = view.scene.edit_group
    context_key = id(context)
    if context_key not in index.context_rows:
        groups = getattr(view.packed, 'groups', None) or ()
        index.context_rows[context_key] = np.array(
            [r for r, group in enumerate(groups) if group is context], np.int64)
    loose_rows = index.context_rows[context_key]
    group_rows = rows[~np.isin(rows, loose_rows)] if len(loose_rows) else rows
    edges = (nearby_edges(index, view.packed, view.camera, view.width(), view.height(),
                         x, y, rows=loose_rows, radius_px=64., cap=400, edit_group=context)
             if len(loose_rows) else [])
    edges += nearby_edges(index, view.packed, view.camera, view.width(), view.height(),
                          x, y, rows=group_rows, edit_group=context)
    tool = getattr(getattr(view, 'tools', None), 'tool', None)
    moving = getattr(tool, '_verts', ()) if getattr(tool, 'grab', None) is not None else ()
    if moving and not getattr(tool, '_copy', False):
        from core.topology import _key
        excluded = {_key(v.position) for v in moving}
        edges = [e for e in edges if e.in_group or
                 (_key(e.a) not in excluded and _key(e.b) not in excluded)]
        point = view.tools.work_point(x, y) or point
        on_face = False
    exclude = getattr(tool, 'snap_excluded', lambda: None)()
    if exclude is not None and exclude[1]:
        edges = [e for e in edges if id(e.group) not in exclude[1]]
    feature_rows = list(dict.fromkeys([e.row for e in edges] + ([row] if row in rows else [])))
    for r in feature_rows:
        value = index.rows.get(r, index.packed.instances[r])
        matrix = value['world'].astype(float).T
        for center in index.features[int(value['info'][0])][0]:
            center = QVector3D(*(matrix[:3, :3] @ center + matrix[:3, 3]))
            edges.append(SimpleNamespace(a=center, b=center, center=True))
        group = view.packed.groups[r] if view.packed.groups is not None else None
        if group is not None and group.is_instance():
            value = index.rows.get(r, index.initial[r])
            anchor = QVector3D(*value['world'][3, :3])
            edges.append(SimpleNamespace(a=anchor, b=anchor, component_origin=True))
    edges = scene_edges(view) + edges
    threshold = options.pop('threshold_px', getattr(view, 'snap_threshold_px', 12.))
    options.setdefault('edge_threshold_px', getattr(view, 'edge_snap_threshold_px', None))
    memo = {}
    def hidden_many(points):
        keys = [p.toTuple() for p in points]
        missing = {key: point for key, point in zip(keys, points) if key not in memo}
        if missing:
            memo.update(zip(missing, _occluded_many(index, view, list(missing.values()), rows)))
        return [memo[key] for key in keys]
    options.setdefault('is_occluded', lambda p: hidden_many([p])[0])
    options.setdefault('are_occluded', hidden_many)
    options.setdefault('face_under_cursor', on_face)
    # Like GL's _pixel_projector: one matrix per query, not per candidate.
    from views.viewport import Viewport
    mvp = view.camera.projection_matrix() * view.camera.view_matrix()
    project = lambda p: Viewport._world_to_pixel(view, p, mvp)
    return compute_snap(point, (x, y), SimpleNamespace(edges=edges),
                        project, threshold, **options)
