# SPDX-License-Identifier: GPL-3.0-or-later
"""Detached project registry views. Persist edits through History."""
from copy import deepcopy
import csv
import io

SECTIONS = ('classification_systems', 'types', 'systems', 'project', 'export_profiles')

def seed_defaults(registry=None):
    r = deepcopy(registry) if registry is not None else {}
    for section in SECTIONS:
        r.setdefault(section, {})
    r['classification_systems'].setdefault('discipline', {
        'name': 'Discipline', 'edition': '', 'source': '',
        'description': 'ISO 19650 UK / US NCS style discipline codes',
        'codes': {code: {'name': name} for code, name in
                  [('A', 'Architectural'), ('S', 'Structural'), ('M', 'Mechanical')]}})
    r['classification_systems'].setdefault('uniclass2015', {
        'name': 'Uniclass 2015', 'edition': '2015',
        'source': 'https://uniclass.thenbs.com/',
        'description': 'NBS Uniclass; import licensed codes supplied by the user.'})
    return r

def get(scene):
    """Return a detached view, seeded only if the document has no registry."""
    stored = scene.plugin_data.get('bim_registry')
    return seed_defaults() if stored is None else deepcopy(stored)

def add_system(registry, key, value, *, classification=False):
    result = deepcopy(registry)
    result.setdefault('classification_systems' if classification else 'systems', {})[key] = deepcopy(value)
    return result

def import_codes_csv(registry, key, text):
    """Merge UTF-8 CSV text atomically; reject duplicates and missing titles."""
    result = deepcopy(registry)
    system = result['classification_systems'][key]
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or not {'code', 'title'} <= set(reader.fieldnames):
        raise ValueError('CSV requires code,title[,parent] columns')
    codes, seen = system.setdefault('codes', {}), set()
    for row in reader:
        code, title = (row.get('code') or '').strip(), (row.get('title') or '').strip()
        if not code or not title or code in seen:
            raise ValueError('CSV has empty or duplicate code/title')
        seen.add(code)
        codes[code] = {'name': title}
        if row.get('parent'):
            codes[code]['parent'] = row['parent'].strip()
    return result

def validate(registry):
    from core.record import validate as validate_record
    if not isinstance(registry, dict):
        return ['Registry must be an object']
    errors = []
    for section in SECTIONS:
        if not isinstance(registry.get(section, {}), dict):
            errors.append(section + ' must be an object')
    if errors:
        return errors
    for section in ('classification_systems', 'systems', 'types', 'export_profiles'):
        for key, value in registry.get(section, {}).items():
            if not isinstance(value, dict):
                errors.append(f'{section}.{key} must be an object')
                continue
            for field in ('name', 'description', 'edition', 'source', 'view', 'object_type'):
                if field in value and not isinstance(value[field], str):
                    errors.append(f'{key}.{field} must be text')
            if section == 'systems' and value.get('ifc_class') not in ('IfcSystem', 'IfcDistributionSystem', 'IfcGroup', 'IfcZone'):
                errors.append(key + ': unsupported system class')
            if section == 'export_profiles':
                if value.get('schema') not in ('IFC4', 'IFC4X3_ADD2'):
                    errors.append(key + ': unsupported export schema')
                paths = value.get('ids_files', [])
                if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                    errors.append(key + ': ids_files must be a list of paths')
            if section == 'types':
                record = {**value, 'class': value.get('ifc_class')}
                errors.extend(key + ': ' + e for e in validate_record(record, registry,
                    'IFC4X3_ADD2' if record['class'] in ('IfcFacility', 'IfcFacilityPart') else 'IFC4'))
            if section == 'classification_systems':
                codes = value.get('codes', {})
                if not isinstance(codes, dict):
                    errors.append(key + ': codes must be an object')
                else:
                    for code, entry in codes.items():
                        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or ('parent' in entry and not isinstance(entry['parent'], str)):
                            errors.append(f'{key}.{code}: invalid code entry')
    for key, value in registry.get('project', {}).items():
        if key in ('name', 'description', 'phase', 'author', 'organization') and not isinstance(value, str):
            errors.append('project.' + key + ' must be text')
    return errors
