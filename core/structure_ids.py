# SPDX-License-Identifier: GPL-3.0-or-later
"""Record-level IDS checks for the structure problems view (2026-11-09).

Only literal entity applicability and record-backed requirements can be decided
before export. Report unsupported facets explicitly so an unchecked spec never
looks like a passing check.
"""
from pathlib import Path
from xml.etree import ElementTree as ET

from core import project, record


def _simple(facet, field):
    return facet.findtext('{*}' + field + '/{*}simpleValue')


def load_requirements(scene, registry):
    requirements = []
    base = project.path_for(scene) or getattr(scene, '_project_host_path', None)
    directory = Path(base).parent if base else Path.cwd()
    for profile, config in registry.get('export_profiles', {}).items():
        if not config.get('ids_files'):
            continue
        eligible = None
        if config.get('filter') is not None:
            from core import facets
            eligible = set(facets.evaluate(facets.build(scene), config['filter']))
        for filename in config['ids_files']:
            ref = dict(profile=profile, file=filename)
            try:
                specs = ET.parse(directory / filename).findall('.//{*}specification')
            except (ET.ParseError, OSError) as exc:
                requirements.append((eligible, None, [], {**ref, 'error': str(exc)}))
                continue
            for spec in specs:
                applies = spec.findall('{*}applicability/*')
                cls = _simple(applies[0], 'name') if len(applies) == 1 else None
                info = {**ref, 'specification': spec.get('name', '')}
                if not cls or applies[0].tag.split('}')[-1] != 'entity' or len(applies[0]) != 1:
                    info['error'] = 'unsupported applicability'
                    cls = None
                requirements.append((eligible, cls, spec.findall('{*}requirements/*'), info))
    return requirements


def _check(facet, rec, registry):
    kind = facet.tag.split('}')[-1]
    fields = {child.tag.split('}')[-1] for child in facet}
    if kind == 'property' and fields <= {'baseName', 'propertySet', 'value'}:
        name, pset = _simple(facet, 'baseName'), _simple(facet, 'propertySet')
        if not name or not pset or 'dataType' in facet.attrib:
            return None
        value = rec.get('psets', {}).get(pset, {}).get(name)
        values = [] if value is None else [value['value']]
    elif kind == 'classification' and fields <= {'system', 'value'}:
        system = _simple(facet, 'system')
        if not system:
            return None
        values = [c.get('code') for c in rec.get('classifications', [])
                  if system in (c['system'], registry.get('classification_systems', {})
                                .get(c['system'], {}).get('name'))]
    else:
        return None
    wanted = _simple(facet, 'value')
    if 'value' in fields and wanted is None:
        return None
    matches = any(wanted is None or str(v) == wanted for v in values)
    cardinality = facet.get('cardinality', 'required')
    if cardinality == 'prohibited':
        return not matches
    return matches or (cardinality == 'optional' and not values)


def requirement_hits(group, registry, requirements):
    if not requirements or not group.ifc:
        return []
    rec = record.apply_type(group.ifc, registry)
    hits = []
    for eligible, cls, facets, info in requirements:
        if eligible is not None and group.uid not in eligible:
            continue
        if cls and rec.get('class', '').upper() != cls.upper():
            continue
        if 'error' in info:
            hits.append({**info, 'uid': group.uid})
            continue
        for facet in facets:
            passed = _check(facet, rec, registry)
            if passed is not True:
                hits.append({**info, 'uid': group.uid, 'facet': facet.tag.split('}')[-1],
                             'status': 'unsupported' if passed is None else 'failed'})
    return hits
