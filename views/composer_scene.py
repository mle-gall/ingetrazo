"""Saved Navigator display state for sheet rendering, without UI side effects."""
from contextlib import contextmanager
from types import SimpleNamespace


@contextmanager
def temporary_display(viewport, saved_view):
    if saved_view is None:
        yield
        return
    from core import bim_registry
    scene = viewport.scene
    key = saved_view.navigator_view
    saved = bim_registry.get(scene).get('views', {}).get(key) if key else None
    keep = (getattr(scene, '_navigator_allowed', None),
            getattr(viewport, 'view_tint', None))
    try:
        # Evaluate against the real scene but run set_display on a shallow
        # facade: it must not change selection, editing context or view epochs.
        from copy import copy
        from core.agent_facets import set_display
        shadow = copy(scene)
        shadow.selection = set(scene.selection)
        shadow.edit_group = None
        proxy = SimpleNamespace(scene=shadow, update=lambda: None)
        if saved is not None:
            set_display(proxy, saved['filter'], saved.get('color_by'),
                        isolate=saved.get('isolate', False), key=key,
                        remember=False, exact=saved.get('exact', False))
            scene._navigator_allowed = shadow._navigator_allowed
            viewport.view_tint = proxy.view_tint
        else:
            scene._navigator_allowed = None
            viewport.view_tint = None
        yield
    finally:
        scene._navigator_allowed, viewport.view_tint = keep
