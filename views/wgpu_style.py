"""Translate display styles without a GPU so both viewports share defaults.

The horizon is supplied by the reference viewport; camera ownership stays there.
Unsupported controls remain explicit in the payload for subsequent passes.
"""
from core.style import Style, effective_back_color


def style_payload(scene, override=None, *, horizon=2.0):
    """Return a fresh native payload, respecting the viewport override."""
    style = override or getattr(scene, 'display_style', None) or Style()
    result = style.to_dict()
    result['back_color'] = effective_back_color(style, scene)
    result['horizon'] = float(horizon)
    return result
