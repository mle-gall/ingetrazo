"""Translate display styles without a GPU so both viewports share defaults.

The horizon is supplied by the reference viewport; camera ownership stays there.
Unsupported controls remain explicit in the payload for subsequent passes.
"""
from core.style import Style, effective_back_color


def style_payload(scene, override=None, *, horizon=2.0, scale=1.0):
    """Return a fresh native payload, respecting the viewport override."""
    style = override or getattr(scene, 'display_style', None) or Style()
    result = style.to_dict()
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
    return result
