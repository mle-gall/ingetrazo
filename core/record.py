# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON object records. All views are detached; reads never assign identities."""
from copy import deepcopy
import math
import re
from core.ifc_tables import TABLES, SCHEMAS, common_pset, predefined_types

KINDS = ('text', 'boolean', 'integer', 'real', 'length', 'area', 'volume', 'enum', 'label')

def typed(value):
    if isinstance(value, dict):
        return deepcopy(value)
    kind = {str: 'text', bool: 'boolean', int: 'integer', float: 'real'}.get(type(value))
    return {'kind': kind, 'value': value}

def normalize(record):
    result = deepcopy(record)
    if isinstance(result, dict) and isinstance(result.get('psets'), dict):
        for properties in result['psets'].values():
            if isinstance(properties, dict):
                for key, value in properties.items():
                    properties[key] = typed(value)
    if isinstance(result, dict) and isinstance(result.get('quantities'), dict):
        for name, value in result['quantities'].items():
            if type(value) in (int, float):
                result['quantities'][name] = {'value': value, 'source': 'manual'}
    return result

def role(record):
    cls = record.get('class')
    if TABLES.get(cls, {}).get('domain') == 'spatial':
        return 'spatial'
    return {'IfcElementAssembly': 'assembly', 'IfcBuildingElementPart': 'part'}.get(cls, 'element')

def apply_type(record, registry):
    """Type scalar defaults; property-level pset overrides; lists replace."""
    # A malformed type reference (unknown key, a non-string, a type entry
    # that is not an object) is a validation problem, not a crash: resolve
    # as if the record had no type, so readers still get a view.
    types = registry.get('types', {})
    key = record.get('type')
    entry = types.get(key) if isinstance(key, str) and isinstance(types, dict) else None
    defaults = deepcopy(entry) if isinstance(entry, dict) else {}
    if 'ifc_class' in defaults:
        defaults['class'] = defaults.pop('ifc_class')
    psets = defaults.pop('psets', {})
    if not isinstance(psets, dict):
        psets = {}
    defaults.update(deepcopy(record))
    own = record.get('psets', {})
    for name, props in (own.items() if isinstance(own, dict) else ()):
        if isinstance(props, dict):
            psets.setdefault(name, {}).update(deepcopy(props))
    if psets:
        defaults['psets'] = psets
    return normalize(defaults)

def validate(record, registry, schema='IFC4'):
    errors = []
    if not isinstance(record, dict):
        return ['record must be an object']
    r = normalize(record)
    cls = r.get('class')
    if schema not in SCHEMAS:
        errors.append('Unsupported schema: ' + str(schema))
    if not isinstance(cls, str) or cls not in TABLES or schema not in TABLES[cls]['schemas']:
        errors.append('class is not supported in ' + schema)
    if type(r.get('v', 1)) is not int or r.get('v', 1) != 1:
        errors.append('v must be 1')
    if 'guid' in r and (not isinstance(r['guid'], str) or not re.fullmatch(r'[0-3][0-9A-Za-z_$]{21}', r['guid'])):
        errors.append('guid must be an IFC compressed GUID')
    for key in ('name', 'description', 'tag', 'object_type'):
        if key in r and not isinstance(r[key], str):
            errors.append(key + ' must be text')
    pt = r.get('predefined_type')
    if pt is not None and pt not in predefined_types(cls if isinstance(cls, str) else '', schema):
        errors.append('predefined_type is not a member for this class/schema')
    if pt == 'USERDEFINED' and not str(r.get('object_type') or '').strip():
        errors.append('USERDEFINED requires object_type')
    key = r.get('type')
    if key is not None and (not isinstance(key, str) or key not in registry.get('types', {})):
        errors.append('Unknown type key')
    systems = r.get('systems', [])
    if not isinstance(systems, list):
        errors.append('systems must be a list')
    else:
        for key in systems:
            if not isinstance(key, str) or key not in registry.get('systems', {}):
                errors.append('Unknown system key: ' + str(key))
    classifications = r.get('classifications', [])
    if not isinstance(classifications, list):
        errors.append('classifications must be a list')
    else:
        for item in classifications:
            if not isinstance(item, dict) or not isinstance(item.get('system'), str) or item['system'] not in registry.get('classification_systems', {}):
                errors.append('Unknown classification system')
            elif any(not isinstance(item.get(k), str) for k in ('code', 'name')):
                errors.append('Classification code and name must be text')
    from core.pset_library import templates
    from xml.etree.ElementTree import ParseError
    try:
        library = templates(registry)
    except (OSError, ValueError, ParseError) as exc:
        errors.append('Cannot read pset library: ' + str(exc))
        library = {}
    psets = r.get('psets', {})
    if not isinstance(psets, dict):
        errors.append('psets must be an object')
    else:
        for pset, props in psets.items():
            if not isinstance(props, dict):
                errors.append(str(pset) + ' must be an object')
                continue
            for prop, value in props.items():
                kind, val = value.get('kind'), value.get('value')
                valid = (kind in KINDS and 'value' in value)
                if kind in ('text', 'label', 'enum'): valid &= isinstance(val, str)
                elif kind == 'boolean': valid &= type(val) is bool
                elif kind == 'integer': valid &= type(val) is int
                else: valid &= type(val) in (int, float) and math.isfinite(val)
                if not valid: errors.append(f'{pset}.{prop}: malformed typed value')
                if pset in library:
                    template = library[pset]['properties'].get(prop)
                    if template is None:
                        errors.append(f'{pset}.{prop}: unknown property')
                    elif 'members' in template and val not in template['members']:
                        errors.append(f'{pset}.{prop}: invalid enumeration member')
                elif isinstance(cls, str) and pset == common_pset(cls):
                    template = TABLES.get(cls, {}).get('common', {}).get(prop, {})
                    members = template.get('members')
                    if members is not None and val not in members:
                        errors.append(f'{pset}.{prop}: invalid enumeration member')
    material = r.get('material')
    if material is not None and not isinstance(material, (str, dict)):
        errors.append('material must be a name or an object')
    if isinstance(material, dict):
        if not isinstance(material.get('name'), str):
            errors.append('material.name must be text')
        layers = material.get('layers', [])
        if not isinstance(layers, list):
            errors.append('material.layers must be a list')
        else:
            for layer in layers:
                if not isinstance(layer, dict) or not isinstance(layer.get('name'), str) or type(layer.get('thickness')) not in (int, float) or not math.isfinite(layer['thickness']) or layer['thickness'] < 0:
                    errors.append('material layer requires a name and nonnegative finite thickness')
    if 'storey' in r and not isinstance(r['storey'], (str, dict)):
        errors.append('storey must be a name or legacy object')
    if isinstance(r.get('storey'), dict):
        info = r['storey']
        if not isinstance(info.get('name'), str) or type(info.get('elevation', 0)) not in (int, float) or not math.isfinite(info.get('elevation', 0)):
            errors.append('storey requires a name and finite elevation')
    if 'fills' in r and (not isinstance(r['fills'], str) or cls not in ('IfcDoor', 'IfcWindow')):
        errors.append('fills requires an opening GUID on a door or window')
    openings = r.get('openings', [])
    if not isinstance(openings, list):
        errors.append('openings must be a list')
    else:
        for opening in openings:
            if not isinstance(opening, dict):
                errors.append('opening must be an object')
                continue
            if opening.get('class', 'IfcOpeningElement') != 'IfcOpeningElement':
                errors.append('opening class must be IfcOpeningElement')
            if 'guid' in opening and (not isinstance(opening['guid'], str) or not re.fullmatch(r'[0-3][0-9A-Za-z_$]{21}', opening['guid'])):
                errors.append('opening guid must be an IFC compressed GUID')
            if 'group_uid' in opening and not isinstance(opening['group_uid'], str):
                errors.append('opening group_uid must be text')
            faces = opening.get('faces', [])
            if not isinstance(faces, list):
                errors.append('opening faces must be a list')
                continue
            for face in faces:
                if not isinstance(face, dict) or not isinstance(face.get('outer'), list):
                    errors.append('opening face requires outer vertices')
                    continue
                if not isinstance(face.get('holes', []), list):
                    errors.append('opening holes must be a list')
                    continue
                loops = [face['outer']] + face.get('holes', [])
                for loop in loops:
                    if not isinstance(loop, list) or len(loop) < 3 or any(not isinstance(p, (list, tuple)) or len(p) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in loop):
                        errors.append('opening loop requires finite world-metre triples')
    quantities = r.get('quantities', {})
    if not isinstance(quantities, dict):
        errors.append('quantities must be an object')
    else:
        for key, value in quantities.items():
            if not isinstance(value, dict) or value.get('source') != 'manual' or type(value.get('value')) not in (int, float) or not math.isfinite(value['value']):
                errors.append(str(key) + ': quantity must be finite and manual')
    return errors

def describe(group):
    return {'uid': group.uid, 'name': group.name, 'record': normalize(group.ifc) if group.ifc else None,
            'role': role(group.ifc or {})}
