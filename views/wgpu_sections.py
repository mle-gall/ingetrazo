"""Resident section polygons using GL's closed-ring and hatch algorithms."""
import math
import numpy as np
from core.section import cut_chords, fill_triangles, hatch_segments, effective_fill


def capture_rows(packed, scene, tint):
    """Resolve saved-frame visibility without baking or changing resident rows."""
    from types import SimpleNamespace
    from views.viewport import Viewport
    from core.group import iter_placements
    from views.wgpu_scene import _placement_state
    state = _placement_state(scene)
    visible = {}
    vp = SimpleNamespace(scene=scene)
    for root in scene.groups:
        inherited = {}
        parents = {}
        def visit(g):
            for child in g.children:
                parents[id(child)] = g
                visit(child)
        visit(root)
        for (group, _), proxy in zip(iter_placements(root), Viewport._expand_placements(vp, root)):
            hidden = inherited.get(id(parents.get(id(group))), False) or not state(proxy)[0]
            inherited[id(group)] = hidden
            visible[id(group)] = not hidden
    rows = packed.instances.copy()
    for i, (uid, group) in enumerate(zip(packed.uids, packed.groups)):
        rows['info'][i, 2] = int(not visible.get(id(group), group is None)) | (8 if getattr(group, 'billboard', False) else 0)
        rgb = (tint or {}).get(uid)
        rows['info'][i, 3] = (int(np.array([*np.clip(np.array(rgb[:3])*255, 0, 255), 255],
                                         np.uint8).view('<u4')[0]) if rgb is not None else 0)
    return rows


def geometry(view, scene, style, camera, height, rows=None):
    """Cache intersections and triangulation; only line widths depend on camera."""
    packed = view.packed
    rows = packed.instances if rows is None else rows
    sp = scene.active_section()
    empty = np.empty(0, np.uint8)
    if sp is None or not getattr(scene, 'show_section_cuts', True):
        return empty
    n = np.array(sp.normal.toTuple(), dtype=float)
    o = np.array(sp.point.toTuple(), dtype=float)
    key = (id(packed), scene.version, tuple(n), tuple(o), rows['info'][:, 2].tobytes())
    cache = getattr(view, '_section_geometry_cache', None)
    if cache is None or cache[0] != key:
        chunks = []
        for row in rows:
            if row['info'][2] & 1:
                continue
            code = int(row['info'][0])
            world = row['world'].T
            lo, hi = packed.bounds[code, 0, :3], packed.bounds[code, 1, :3]
            center = world[:3, :3] @ ((lo+hi)*.5) + world[:3, 3]
            radius = np.abs(n @ world[:3, :3]) @ ((hi-lo)*.5)
            if abs(n @ (center-o)) > radius:
                continue
            cmd = packed.commands[code]
            start = int(cmd['base'])
            tri = packed.vertices['pos'][start:start+int(cmd['count'])].reshape(-1, 3, 3) @ world[:3, :3].T + world[:3, 3]
            segs = cut_chords(tri[:, 0], tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0], sp.normal, sp.point)
            if segs is not None and len(segs):
                chunks.append(segs)
        segs = np.concatenate(chunks) if chunks else np.empty((0, 2, 3))
        cache = (key, segs, fill_triangles(segs, sp.normal), {})
        view._section_geometry_cache = cache
    _, segs, fill, hatches = cache
    pattern, color, spacing = effective_fill(sp, style)
    render_key = (key, pattern, color, spacing, style.face_mode, tuple(style.edge_color),
                  tuple(camera.eye().toTuple()), camera.fov_deg, height)
    if getattr(view, '_section_render_key', None) == render_key:
        return view._section_render_data
    chunks = []
    def add(points, rgb):
        if points is not None and len(points):
            points = np.asarray(points).reshape(-1, 3)
            chunks.append(np.column_stack((points, np.broadcast_to(rgb[:3], points.shape))))
    eye = np.array(camera.eye().toTuple())
    def lines(segments, rgb, half_width, lift):
        if segments is None or not len(segments):
            return
        a, b = segments[:, 0], segments[:, 1]
        t = b-a
        length = np.linalg.norm(t, axis=1)
        keep = length > 1e-9
        a, b, t, length = a[keep], b[keep], t[keep], length[keep]
        wpp = np.maximum(np.linalg.norm((a+b)*.5-eye, axis=1) * math.tan(math.radians(camera.fov_deg)*.5)*2/max(1, height), 1e-6)
        w = (wpp * half_width)[:, None]
        side = np.cross(n, t/length[:, None])*w
        offset = n*lift*w
        q0, q1, q2, q3 = a-side+offset, b-side+offset, b+side+offset, a+side+offset
        add(np.stack((q0, q1, q2, q0, q2, q3), axis=1), rgb)
    if style.face_mode not in ('xray', 'wireframe') and pattern != 'none':
        base = color if pattern == 'solid' else tuple(c+(1-c)*.78 for c in color[:3])
        add(fill, base)
        if pattern in ('hatch', 'cross'):
            hatch_key = (spacing, pattern == 'cross')
            if hatch_key not in hatches:
                hatches[hatch_key] = hatch_segments(segs, sp.normal, *hatch_key)
            lines(hatches[hatch_key], color, .5, .01)
    lines(segs, style.edge_color, 1.25, .6)
    result = np.concatenate(chunks).astype('<f4').view(np.uint8).reshape(-1) if chunks else empty
    view._section_render_key, view._section_render_data = render_key, result
    return result


def sync(view):
    from core.style import Style
    source = view.source_viewport
    style = source._effective_style() if source is not None else getattr(view.scene, 'display_style', Style())
    data = geometry(view, view.scene, style, view.camera, view.height())
    if data is not getattr(view, '_section_uploaded', None):
        view.renderer.set_section_geometry(data)
        view._section_uploaded = data
