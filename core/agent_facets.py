# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Navigator actions for the bridge and the dock."""
from copy import deepcopy
from core import facets, bim_registry
from core.history import SetRegistryCommand


def set_display(viewport, filter=None, color_by=None, *, isolate=True, key=None, remember=True, exact=False):
    index = facets.build(viewport.scene)
    uids = facets.evaluate(index, filter)
    tint = None
    if color_by:
        index.prepare(color_by)
        tint = {uid: facets.palette(row[color_by]) for uid, row in index.items()
                if row.get(color_by) not in (None, [], '')}
    if remember:
        previous = getattr(viewport, '_previous_views', [])
        previous.append((deepcopy(getattr(viewport, '_view_expression', None)),
                         getattr(viewport, '_view_color', None),
                         getattr(viewport, '_view_isolate', True),
                         getattr(viewport, 'active_view_key', None),
                         getattr(viewport, '_view_exact', False)))
        viewport._previous_views = previous[-10:]
    viewport._view_expression = deepcopy(filter)
    viewport._view_color = color_by
    viewport._view_isolate = isolate
    viewport._view_exact = exact
    viewport.active_view_key = key
    viewport.scene._navigator_view_key = key
    viewport.view_filter = set(uids) if filter is not None and isolate else None
    # Expand once; drawing and picking then share an O(1) membership test.
    allowed = None if viewport.view_filter is None else {
        uid for uid, row in index.items()
        if uid in viewport.view_filter or (not exact and any(p in viewport.view_filter for p in row['path_uids']))}
    viewport.scene._navigator_allowed = allowed
    inherited = {}
    for uid, row in index.items():
        if tint and uid in tint:
            inherited[uid] = tint[uid]
        elif row['path_uids'] and row['path_uids'][-1] in inherited:
            inherited[uid] = inherited[row['path_uids'][-1]]
    viewport.view_tint = inherited or None
    viewport._navigator_revision = getattr(viewport, '_navigator_revision', 0) + 1
    viewport._epoch_memo = None
    viewport.scene.bump_view()
    viewport.update()
    return uids


def previous_display(viewport):
    previous = getattr(viewport, '_previous_views', [])
    if previous:
        expr, color, isolate, key, exact = previous.pop()
        set_display(viewport, expr, color, isolate=isolate, key=key, remember=False, exact=exact)


class FacetTools:
    def _tool_query_facets(self, filter=None, facets=None):
        index = globals()['facets'].build(self._viewport.scene)
        uids = globals()['facets'].evaluate(index, filter)
        names = facets or sorted({k for row in index.values() for k in row})
        return {name: globals()['facets'].values(index, name, uids) for name in names}

    def _tool_query_view(self, filter=None, offset=0, limit=200):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('offset must be nonnegative and limit 1..1000')
        index = facets.build(self._viewport.scene)
        uids = facets.evaluate(index, filter)
        rows = []
        for uid in uids[offset:offset + limit]:
            row = index[uid]
            rows.append(dict(uid=uid, **{k: row[k] for k in ('name', 'path', 'class', 'tag', 'hidden')},
                             kinds={k[5:]: v for k, v in row.items() if k.startswith('kind:')}))
        return dict(rows=rows, total=len(uids), next_offset=offset + limit if offset + limit < len(uids) else None)

    def _tool_set_view_filter(self, filter=None, color_by=None):
        return dict(uids=set_display(self._viewport, filter, color_by))

    def _save_navigator_entry(self, section, key, value):
        if not isinstance(key, str) or not key:
            raise ValueError('key must be nonempty text')
        registry = bim_registry.get(self._viewport.scene)
        registry.setdefault(section, {})[key] = deepcopy(value)
        errors = bim_registry.validate(registry)
        if errors:
            raise ValueError('; '.join(errors))
        self._viewport.history.execute(SetRegistryCommand(registry))
        return dict(key=key)

    def _tool_save_view(self, key, name, filter, color_by=None, isolate=False):
        return self._save_navigator_entry('views', key, dict(name=name, filter=filter, color_by=color_by, isolate=isolate))

    def _tool_apply_view(self, key):
        view = bim_registry.get(self._viewport.scene)['views'][key]
        return dict(uids=set_display(self._viewport, view['filter'], view.get('color_by'),
                                    isolate=view.get('isolate', False), key=key))

    def _tool_set_rule(self, key, value):
        return self._save_navigator_entry('rules', key, value)

    def _tool_apply_rule(self, key):
        vp = self._viewport
        uids = facets.apply_rule(vp.scene, vp.history, bim_registry.get(vp.scene), key)
        vp.refresh_after_edit()
        return dict(uids=uids)
