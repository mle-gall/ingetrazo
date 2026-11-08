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
    return result

def role(record):
    cls = record.get('class')
    if cls in ('IfcSite', 'IfcBuilding', 'IfcBuildingStorey', 'IfcSpace', 'IfcSpatialZone', 'IfcFacility', 'IfcFacilityPart'):
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
                if isinstance(cls, str) and pset == common_pset(cls):
                    template = TABLES.get(cls, {}).get('common', {}).get(prop, {})
                    members = template.get('members')
                    if members is not None and val not in members:
                        errors.append(f'{pset}.{prop}: invalid enumeration member')
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
