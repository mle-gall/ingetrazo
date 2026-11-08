# SPDX-License-Identifier: GPL-3.0-or-later
"""One ordered metadata index for navigation, saved views and classification rules.

Geometry-derived fields are lazy: browsing names must never instantiate deferred
meshes. The cache follows the inspection bridge's document revision contract.
"""
from collections import Counter
from copy import deepcopy
from fnmatch import fnmatchcase
import colorsys
import hashlib
import json
import weakref

_DEFINITIONS = weakref.WeakKeyDictionary()


class Index(dict):
    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        self.groups = {}
        self.lazy = set()

    def prepare(self, facet):
        if facet not in ('material', 'problems') or facet in self.lazy:
            return
        from core import record, bim_registry
        registry = bim_registry.get(self.scene)
        materials = {}
        for uid, row in self.items():
            group = self.groups[uid]
            if facet == 'problems':
                row[facet] = len(record.validate(group.ifc, registry)) if group.ifc else 0
            elif not row['material']:
                mesh = group.mesh
                if mesh not in materials:
                    areas = Counter()
                    for face in mesh.faces:
                        name = face.attrs.get('mat')
                        if name:
                            areas[name] += face.area()
                    materials[mesh] = areas.most_common(1)[0][0] if areas else None
                row[facet] = materials[mesh]
        self.lazy.add(facet)


def build(scene):
    key = (id(scene), scene.version, len(scene.groups))
    cached = getattr(scene, '_facet_index', None)
    if cached and cached[0] == key:
        return cached[1]
    from core.links import link_of
    from core.record import role
    index = Index(scene)
    layers = {layer.name: layer for layer in scene.layers}

    def walk(groups, names, uids, spatial=None, source=None):
        for group in groups:
            rec = group.ifc or {}
            link = link_of(group)
            src = link['path'] if link else source
            mesh = group.mesh
            if mesh not in _DEFINITIONS:
                _DEFINITIONS[mesh] = str(len(_DEFINITIONS) + 1) + ':' + str(id(mesh))
            layer = layers.get(group.layer)
            material = rec.get('material')
            storey = rec.get('storey') or spatial
            row = dict(uid=group.uid, problems=None, name=group.name, path='/'.join(names), path_uids=list(uids),
                       depth=len(uids), definition=group.name + ' [' + _DEFINITIONS[mesh] + ']',
                       instance=group.xform is not None, tag=group.layer,
                       tag_uid=layer.uid if layer else None,
                       tag_folder=getattr(layer, 'folder', None), hidden=bool(group.hidden),
                       linked=src is not None, link_source=src,
                       predefined_type=rec.get('predefined_type'), system=rec.get('systems', []),
                       type=rec.get('type'), storey=storey.get('name') if isinstance(storey, dict) else storey,
                       status=None, material=material.get('name') if isinstance(material, dict) else material)
            row['class'] = rec.get('class')
            for item in rec.get('classifications', []):
                row.setdefault('kind:' + item['system'], []).append(item['code'])
            for name, pset in rec.get('psets', {}).items():
                if name.endswith('Common') and 'Status' in pset:
                    value = pset['Status']
                    row['status'] = value.get('value') if isinstance(value, dict) else value
            index[group.uid] = row
            index.groups[group.uid] = group
            walk(group.children or [], names + [group.name], uids + [group.uid],
                 group.name if role(rec) == 'spatial' else spatial, src)
    walk(scene.groups, [], [])
    scene._facet_index = (key, index)
    return index


def validate_filter(value):
    """Reject ambiguous expressions before inspecting any model data."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError('filter must be an object or null')
    keys = set(value)
    if keys in ({'all'}, {'any'}):
        children = next(iter(value.values()))
        if not isinstance(children, list):
            raise ValueError('all/any require a list')
        for child in children:
            validate_filter(child)
        return
    if keys == {'not'}:
        validate_filter(value['not'])
        return
    if keys == {'text'} and isinstance(value['text'], str):
        return
    ops = keys - {'facet'}
    if 'facet' not in keys or not isinstance(value['facet'], str) or len(ops) != 1:
        raise ValueError('leaf requires facet and one operator')
    op = next(iter(ops))
    v = value[op]
    if op not in ('eq', 'in', 'glob', 'exists', 'gt', 'lt'):
        raise ValueError('unknown filter operator')
    if (op == 'in' and (not isinstance(v, list) or any(isinstance(x, (dict, list)) for x in v))
            or op == 'glob' and not isinstance(v, str)
            or op == 'exists' and type(v) is not bool
            or op in ('gt', 'lt') and type(v) not in (int, float)
            or op == 'eq' and isinstance(v, (dict, list))):
        raise ValueError('invalid filter operand')


def _compile(index, expr):
    if expr is None:
        return lambda row: True
    if 'all' in expr or 'any' in expr:
        op = 'all' if 'all' in expr else 'any'
        children = [_compile(index, child) for child in expr[op]]
        combine = all if op == 'all' else any
        return lambda row: combine(f(row) for f in children)
    if 'not' in expr:
        child = _compile(index, expr['not'])
        return lambda row: not child(row)
    if 'text' in expr:
        pattern = expr['text'].casefold()
        return lambda row: any(fnmatchcase(str(row[k]).casefold(), pattern) for k in ('name', 'path'))
    facet = expr['facet']
    index.prepare(facet)
    op = next(k for k in expr if k != 'facet')
    operand = expr[op]
    if op == 'glob':
        operand = operand.casefold()
    if op == 'in':
        operand = set(operand)
    def match(row):
        value = row.get(facet)
        if op == 'exists':
            return (value is not None and value != [] and value != '') == operand
        items = value if isinstance(value, list) else [value]
        if op == 'eq':
            return operand in items
        if op == 'in':
            return any(v in operand for v in items)
        if op == 'glob':
            return any(isinstance(v, str) and fnmatchcase(v.casefold(), operand) for v in items)
        return any(type(v) in (float, int) and (v > operand if op == 'gt' else v < operand) for v in items)
    return match


def evaluate(index, filter=None):
    validate_filter(filter)
    match = _compile(index, filter)
    return [uid for uid, row in index.items() if match(row)]


def values(index, facet, uids=None):
    index.prepare(facet)
    counts = Counter()
    for uid in index if uids is None else uids:
        value = index[uid].get(facet)
        for v in set(value if isinstance(value, list) else [value]):
            if v is not None:
                counts[v] += 1
    return dict(counts)


def palette(value):
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()
    return colorsys.hsv_to_rgb(int.from_bytes(digest[:4], 'big') / 2**32, .55, .85)


def apply_rule(scene, history, registry, key):
    from core.history import CompoundCommand, SetRecordCommand
    from core.record import validate
    rule = registry['rules'][key]
    index = build(scene)
    uids = evaluate(index, rule['filter'])
    commands = []
    for uid in uids:
        if index[uid]['linked']:
            raise ValueError('Linked objects must be classified in their source file')
        group = index.groups[uid]
        patch = deepcopy(rule['apply'].get('patch', {}))
        items = deepcopy(patch.get('classifications', (group.ifc or {}).get('classifications', [])))
        for item in rule['apply'].get('classifications', []):
            items = [c for c in items if (c['system'], c['code']) != (item['system'], item['code'])]
            items.append(deepcopy(item))
        if items:
            patch['classifications'] = items
        errors = validate({**(group.ifc or {}), **patch}, registry)
        if errors:
            raise ValueError('; '.join(errors))
        commands.append(SetRecordCommand([group], patch))
    if commands:
        history.execute(CompoundCommand(commands))
    return uids
