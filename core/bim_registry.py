# SPDX-License-Identifier: GPL-3.0-or-later
"""Detached project registry views. Persist edits through History."""
from copy import deepcopy
import csv
import io

SECTIONS = ('classification_systems', 'types', 'systems', 'project', 'export_profiles', 'tag_sets', 'storeys', 'pset_library', 'views', 'rules', 'structure')

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
    from core.project import read
    project = read(scene)
    stored = project['bim_registry'] if project else scene.plugin_data.get('bim_registry')
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

def _structure_errors(registry):
    """Validate inherited constraints too: a parent edit can invalidate a leaf."""
    from core.ifc_tables import TABLES, predefined_types
    section = registry.get('structure', {})
    nodes = section.get('nodes', {})
    if not isinstance(nodes, dict):
        return ['structure.nodes must be an object']

    def known(key, mapping):
        return isinstance(key, str) and key in mapping

    errors = []
    if 'active' in section and not known(section['active'], nodes):
        errors.append('structure.active must name a node')
    for key, node in nodes.items():
        prefix = f'structure.nodes.{key}: '
        if not isinstance(key, str) or not key or not isinstance(node, dict):
            errors.append(prefix + 'expected a named node object')
            continue
        if not isinstance(node.get('name'), str) or not node['name'].strip():
            errors.append(prefix + 'name must be nonempty text')
        if type(node.get('order')) is not int:
            errors.append(prefix + 'order must be an integer')
        lineage = []
        seen = set()
        ancestor = key
        while ancestor is not None:
            if not known(ancestor, nodes) or not isinstance(nodes[ancestor], dict):
                errors.append(prefix + 'unknown parent')
                break
            if ancestor in seen:
                errors.append(prefix + 'parent cycle')
                break
            seen.add(ancestor)
            lineage.append(nodes[ancestor])
            ancestor = nodes[ancestor].get('parent', False)
        recipe = node.get('recipe', {})
        if not isinstance(recipe, dict):
            errors.append(prefix + 'recipe must be an object')
            continue
        effective = {}
        for item in reversed(lineage):
            if isinstance(item.get('recipe'), dict):
                effective.update(item['recipe'])
        cls = effective.get('class')
        if cls is not None and not known(cls, TABLES):
            errors.append(prefix + 'unknown class')
        allowed = effective.get('classes_allowed')
        if 'classes_allowed' in effective and (
                not isinstance(allowed, list) or any(not known(c, TABLES) for c in allowed)
                or (cls is not None and cls not in allowed)):
            errors.append(prefix + 'invalid classes_allowed')
        pt = effective.get('predefined_type')
        if pt is not None and (not known(cls, TABLES) or not any(
                pt in predefined_types(cls, schema) for schema in TABLES[cls]['schemas'])):
            errors.append(prefix + 'invalid predefined_type')
        for field in ('tag', 'object_type'):
            if field in recipe and not isinstance(recipe[field], str):
                errors.append(prefix + field + ' must be text')
        if 'tag' in recipe and not recipe['tag']:
            errors.append(prefix + 'tag must be nonempty')
        folder = recipe.get('folder', [])
        if not isinstance(folder, (str, list)) or (isinstance(folder, list)
                and any(not isinstance(f, str) or not f for f in folder)):
            errors.append(prefix + 'folder must be a name or path of names')
        if recipe.get('type') is not None and not known(recipe['type'], registry.get('types', {})):
            errors.append(prefix + 'unknown type')
        systems = recipe.get('systems', [])
        if not isinstance(systems, list) or any(not known(k, registry.get('systems', {})) for k in systems):
            errors.append(prefix + 'invalid systems')
        items = recipe.get('classifications', [])
        namespaces = registry.get('classification_systems', {})
        if not isinstance(items, list):
            errors.append(prefix + 'classifications must be a list')
        else:
            for item in items:
                ns = item.get('system') if isinstance(item, dict) else None
                entry = namespaces.get(ns) if isinstance(ns, str) else None
                codes = entry.get('codes') if isinstance(entry, dict) else None
                if not isinstance(codes, dict) or not known(item.get('code'), codes):
                    errors.append(prefix + 'unknown classification system/code')
        props = recipe.get('psets', {})
        if not isinstance(props, dict) or any(not isinstance(p, dict) for p in props.values()):
            errors.append(prefix + 'psets must map names to property maps')
    return errors


def validate(registry):
    from core.record import validate as validate_record
    from core.ifc_tables import TABLES, predefined_types
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
                    next(iter(TABLES.get(record['class'], {}).get('schemas', ['IFC4'])))))
            if section == 'classification_systems':
                codes = value.get('codes', {})
                if not isinstance(codes, dict):
                    errors.append(key + ': codes must be an object')
                else:
                    for code, entry in codes.items():
                        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or ('parent' in entry and not isinstance(entry['parent'], str)):
                            errors.append(f'{key}.{code}: invalid code entry')
    from core.facets import validate_filter
    for section in ('views', 'rules', 'export_profiles'):
        for key, value in registry.get(section, {}).items():
            if not isinstance(value, dict):
                errors.append(key + ': entry must be an object')
                continue
            try:
                validate_filter(value.get('filter'))
            except ValueError as exc:
                errors.append(key + ': ' + str(exc))
            if section == 'export_profiles':
                continue
            if not isinstance(value.get('name'), str) or 'filter' not in value:
                errors.append(key + ': name and filter required')
            if section == 'views':
                if value.get('color_by') is not None and not isinstance(value['color_by'], str):
                    errors.append(key + ': color_by must be text or null')
                if type(value.get('isolate', False)) is not bool:
                    errors.append(key + ': isolate must be boolean')
            else:
                apply = value.get('apply')
                if not isinstance(apply, dict) or not isinstance(apply.get('patch', {}), dict):
                    errors.append(key + ': apply requires a record patch')
                    continue
                items = apply.get('classifications', [])
                if not isinstance(items, list) or any(not isinstance(c, dict) or
                        any(not isinstance(c.get(k), str) for k in ('system', 'code', 'name')) for c in items):
                    errors.append(key + ': invalid classifications')
    defaults = 0
    for key, value in registry.get('tag_sets', {}).items():
        if not isinstance(value, dict) or not isinstance(value.get('classes'), list):
            errors.append(key + ': tag set requires classes')
            continue
        defaults += value.get('default') is True
        for field in ('name', 'description'):
            if field in value and not isinstance(value[field], str):
                errors.append(key + ': ' + field + ' must be text')
        if type(value.get('default', False)) is not bool:
            errors.append(key + ': default must be boolean')
        for entry in value['classes']:
            if not isinstance(entry, dict) or entry.get('class') not in TABLES:
                errors.append(key + ': unknown class')
                continue
            cls = entry['class']
            if entry.get('predefined_type') and not any(entry['predefined_type'] in predefined_types(cls, schema) for schema in TABLES[cls]['schemas']):
                errors.append(key + ': invalid predefined_type')
            if 'kinds' in entry and (not isinstance(entry['kinds'], list) or any(not isinstance(k, str) for k in entry['kinds'])):
                errors.append(key + ': kinds must be text codes')
    if defaults > 1:
        errors.append('Only one tag set may be default')
    import math
    for name, value in registry.get('storeys', {}).items():
        elevation = value.get('elevation', 0) if isinstance(value, dict) else None
        if type(elevation) not in (float, int) or not math.isfinite(elevation):
            errors.append(name + ': elevation must be finite metres')
    if 'path' in registry.get('pset_library', {}) and not isinstance(registry['pset_library']['path'], str):
        errors.append('pset_library.path must be text')
    for key, value in registry.get('project', {}).items():
        if key in ('name', 'description', 'phase', 'author', 'organization') and not isinstance(value, str):
            errors.append('project.' + key + ' must be text')
    return errors + _structure_errors(registry)


def ordered_classes(registry):
    """Default project choices precede the stable baseline vocabulary."""
    from core.ifc_tables import IFC_CLASSES
    preferred = [entry['class'] for value in registry.get('tag_sets', {}).values()
                 if value.get('default') for entry in value.get('classes', [])]
    return list(dict.fromkeys(preferred + IFC_CLASSES))
