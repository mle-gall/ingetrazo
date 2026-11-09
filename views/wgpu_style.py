"""Translate display styles without a GPU so both viewports share defaults.

The horizon is supplied by the reference viewport; camera ownership stays there.
Unsupported controls remain explicit in the payload for subsequent passes.
"""
from core.style import Style, effective_back_color


def style_payload(scene, override=None, *, horizon=2.0, scale=1.0, edit_rest_fade=0.0):
    """Return a fresh native payload, respecting the viewport override."""
    style = override or getattr(scene, 'display_style', None) or Style()
    result = style.to_dict()
    from views.viewport import edit_fade_color
    result['fade'] = float(edit_rest_fade)
    result['fade_color'] = edit_fade_color(style.background)
    result['back_color'] = effective_back_color(style, scene)
    from views.ambient_occlusion import settings_for
    ao = settings_for(style)
    result['ambient_occlusion'] = ao is not None
    if ao is not None:
        result.update(ao_distance=ao['radius'], ao_intensity=ao['intensity'],
                      ao_samples=ao['samples'])
    result['horizon'] = float(horizon)
    result['profile_width'] = float(getattr(style, 'profile_width', 1.0))
    result['dash_width'] = 4.0 * max(1.0, float(scale))
    # R3c-2a: GL keeps dot(normal, world - point) <= 0.
    active = getattr(scene, 'active_section', lambda: None)()
    plane = (0., 0., 0., 0.)
    if active is not None and getattr(scene, 'show_section_cuts', True):
        n, o = active.normal, active.point
        plane = (-n.x(), -n.y(), -n.z(),
                 n.x()*o.x() + n.y()*o.y() + n.z()*o.z())
    result['section_plane'] = plane
    # TODO(P3): enable material_opacity once the alpha-byte bake is installed.
    # The opt-in preserves legacy byte 254 (two-sided paint provenance).
    result['material_opacity'] = bool(getattr(scene, 'wgpu_material_opacity', False))
    result['group_selection_edges'] = True
    result['show_hidden_geometry'] = bool(getattr(scene, 'show_hidden_geometry', False))
    result['show_hidden_objects'] = bool(getattr(scene, 'show_hidden_objects', False))
    result.update(sun_payload(scene, override=override))
    return result


def sun_payload(scene, *, override=None):
    """Same sun/date/north convention and GL light fit; no viewport required."""
    import datetime
    import os
    from core import sun
    from views.viewport import Viewport
    result = dict(shadows=False, sun_direction=(0., 0., 1.),
                  shadow_darkness=0.55, ground_shadows=True)
    sh = getattr(scene, 'shadows', None)
    if getattr(override, 'name', None) in ('tecnico', 'lineas') or os.environ.get('INGETRAZO_NO_SHADOWS') or not getattr(sh, 'enabled', False):
        return result
    datum = getattr(scene, 'georef', None)
    lat, lon = getattr(datum, 'lat', None), getattr(datum, 'lon', None)
    if lat is None or lon is None:
        lat, lon = sun.DEFAULT_LAT, sun.DEFAULT_LON
    try:
        direction = sun.sun_direction(lat, lon, sh.when_utc(lon, year=datetime.date.today().year))
    except ValueError:
        return result
    if direction is None:
        return result
    if datum is not None and getattr(datum, 'north', 0.):
        x, y = datum.grid_to_local_xy(direction[0], direction[1])
        direction = (x, y, direction[2])
    lo, hi = scene.bounds()
    if lo is None:
        return result
    result.update(shadows=True, sun_direction=tuple(direction),
                  shadow_darkness=float(getattr(sh, 'darkness', 0.55)),
                  shadow_matrix=list(Viewport._light_vp(direction, lo, hi).data()))
    # TODO(P1): suppress the ground catcher when a visible reference ground
    # (map/terrain/photo mesh) supplies the receiver, matching GL's predicates.
    return result
