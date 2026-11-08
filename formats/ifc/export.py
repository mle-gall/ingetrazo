# SPDX-License-Identifier: GPL-3.0-or-later
"""Export records and registry relationships without a native IFC dependency."""
import datetime
import math
import uuid
from collections import defaultdict
from pathlib import Path

from core import bim_registry, record
from core.bim import (collect_objects, class_quantities, class_quantities_arrays,
                      _placed_groups, _compose)
from core.ifc_identity import object_guid, stable_guid
from core.ifc_tables import TABLES, predefined_types
from core.version import __version__
from .entities import Builder
from core.ifc_tables_data import SCHEMA_DATA
from .relationships import Appearance
from .geometry import array_body, mapped_body
from core.geometry_arrays import (world_arrays, merged, faces_arrays,
                                  quantities as array_quantities, measurements,
                                  face_attributes, recorded_arrays)
from .step import _s, _f
from .ids import check_ids


class ExportReport(int):
    """An integer-compatible count for existing callers, with diagnostic details."""
    def __new__(cls, count, path, problems, ids, linked_skipped=0):
        result = super().__new__(cls, count)
        result.count = count
        result.path = str(path)
        result.problems = problems
        result.ids = ids
        result.linked_skipped = linked_skipped
        return result


def ref(value):
    return f'#{value}'


def refs(values):
    return '(' + ','.join(map(ref, values)) + ')'


def save_ifc(scene, path, project_name='IngeTrazo project', profile=None, *, project_directory=None):
    with open(path, 'w', encoding='ascii', buffering=1024 * 1024) as stream:
        report = _save_ifc(scene, path, project_name, profile, stream)
    registry = bim_registry.get(scene)
    config = registry.get('export_profiles', {}).get(profile, {}) if profile else {}
    report.ids = check_ids(path, config.get('ids_files', []), project_directory)
    return report


def _save_ifc(scene, path, project_name, profile, stream):
    registry = bim_registry.get(scene)
    config = registry.get('export_profiles', {}).get(profile, {}) if profile else {}
    if profile and profile not in registry.get('export_profiles', {}):
        raise ValueError('Unknown export profile: ' + profile)
    geometry = config.get('geometry', 'brep')
    if geometry not in ('brep', 'polygonal'):
        raise ValueError('Unsupported geometry: ' + geometry)
    schema = config.get('schema', 'IFC4')
    if schema not in ('IFC4', 'IFC4X3_ADD2'):
        raise ValueError('Unsupported schema: ' + schema)
    # Content placed from a linked file is that file's deliverable: the host
    # leaves it out unless the profile says ``include_links``.
    from core.links import is_linked
    include_links = bool(config.get('include_links', False))
    objects = collect_objects(scene)
    linked_skipped = 0
    if not include_links:
        linked_ids = set()
        def mark(groups, inside):
            for g in groups:
                here = inside or is_linked(g)
                if here:
                    linked_ids.add(id(g))
                mark(g.children or [], here)
        mark(scene.groups, False)
        kept = []
        for obj in objects:
            host = obj.get('group') if obj.get('group') is not None else obj.get('owner')
            if host is not None and id(host) in linked_ids:
                linked_skipped += 1
            else:
                kept.append(obj)
        objects = kept
    if config.get('filter') is not None:
        from core.facets import build, evaluate
        allowed = set(evaluate(build(scene), config['filter']))
        objects = [obj for obj in objects
                   if getattr(obj.get('group') if obj.get('group') is not None else obj.get('owner'), 'uid', None) in allowed]
    if not objects:
        raise ValueError('No tagged BIM objects to export')
    identity = scene.plugin_data.setdefault('ifc_identity', {})
    if not identity.get('namespace'):
        identity['namespace'] = uuid.uuid4().hex
        scene.version += 1

    def guid(*parts):
        value = stable_guid(identity['namespace'], *parts)
        if len(parts) == 1 and parts[0] in ('project', 'site', 'building', 'storey'):
            if parts[0] not in identity:
                identity[parts[0]] = value
                scene.version += 1
            return identity[parts[0]]
        return value

    owner = '$'
    project_data = registry.get('project', {})
    author = project_data.get('author', '')
    organization = project_data.get('organization', '')
    stamp = datetime.datetime.now().isoformat(timespec='seconds')
    view = config.get('view', 'ReferenceView')
    if view == 'ReferenceView' and schema == 'IFC4':
        view = 'ReferenceView_V1.2'
    header = ("ISO-10303-21;\nHEADER;\n"
              f"FILE_DESCRIPTION(({_s('ViewDefinition [' + view + ']')}),'2;1');\n"
              f"FILE_NAME({_s(Path(path).name)},{_s(stamp)},({_s(author)}),({_s(organization)}),"
              f"{_s('IngeTrazo ' + __version__)},'IngeTrazo','');\n"
              f"FILE_SCHEMA(('{schema}'));\nENDSEC;\nDATA;\n")
    stream.write(header)
    w = Builder(schema, stream)
    if author or organization:
        person = w.entity('IfcPerson', FamilyName=_s(author or organization))
        org = w.entity('IfcOrganization', Name=_s(organization or author))
        user = w.entity('IfcPersonAndOrganization', ThePerson=ref(person), TheOrganization=ref(org))
        app = w.entity('IfcApplication', ApplicationDeveloper=ref(org), Version=_s(__version__),
                       ApplicationFullName=_s('IngeTrazo'), ApplicationIdentifier=_s('IngeTrazo'))
        owner = ref(w.entity('IfcOwnerHistory', OwningUser=ref(user), OwningApplication=ref(app),
                             ChangeAction='.NOCHANGE.', CreationDate=str(int(datetime.datetime.now().timestamp()))))

    def root(entity, key, **attrs):
        return w.entity(entity, GlobalId=_s(guid(*key)), OwnerHistory=owner, **attrs)

    def relation(entity, key, **attrs):
        return root(entity, (entity, *key), **attrs)

    origin = w.add('IFCCARTESIANPOINT', '(0.,0.,0.)')
    axis = w.add('IFCAXIS2PLACEMENT3D', ref(origin), '$', '$')
    context = w.add('IFCGEOMETRICREPRESENTATIONCONTEXT', '$', "'Model'", '3', '1.E-5', ref(axis), '$')
    body = w.add('IFCGEOMETRICREPRESENTATIONSUBCONTEXT', "'Body'", "'Model'", '*', '*', '*', '*',
                 ref(context), '$', '.MODEL_VIEW.', '$')
    units = [w.add('IFCSIUNIT', '*', '.' + kind + 'UNIT.', prefix, '.' + unit + '.')
             for kind, prefix, unit in [('LENGTH', '$', 'METRE'), ('AREA', '$', 'SQUARE_METRE'),
                                       ('VOLUME', '$', 'CUBIC_METRE'), ('MASS', '.KILO.', 'GRAM'),
                                       ('PLANEANGLE', '$', 'RADIAN')]]
    ua = w.add('IFCUNITASSIGNMENT', refs(units))
    placement = w.add('IFCLOCALPLACEMENT', '$', ref(axis))
    project = root('IfcProject', ('project',), Name=_s(project_data.get('name') or project_name),
                   Description=_s(project_data.get('description', '')), Phase=_s(project_data.get('phase', '')),
                   RepresentationContexts=refs([context]), UnitsInContext=ref(ua))
    defaults = {}
    parent = project
    for key, cls in [('site', 'IfcSite'), ('building', 'IfcBuilding'), ('storey', 'IfcBuildingStorey')]:
        attrs = dict(Name=_s(key.title()), ObjectPlacement=ref(placement), CompositionType='.ELEMENT.')
        if key == 'storey':
            attrs['Elevation'] = '0.'
        node = root(cls, (key,), **attrs)
        relation('IfcRelAggregates', ('default', key), RelatingObject=ref(parent), RelatedObjects=refs([node]))
        defaults[key] = node
        parent = node

    appearance = Appearance(scene, w, relation)
    opening_nodes = {}
    pending_fills = []
    problems = []
    classifications = defaultdict(list)
    classification_names = {}
    type_members = defaultdict(list)
    system_members = defaultdict(list)
    group_nodes = {}
    exported = []
    bases = {id(g): base for g, base in _placed_groups(scene.groups)}
    parents = {}
    def walk(groups, parent=None):
        for group in groups:
            parents[id(group)] = parent
            walk(group.children, group)
    walk(scene.groups)

    def psets(data, key):
        result = []
        for name, props in data.items():
            values = []
            for prop, value in props.items():
                kind, val = value['kind'], value['value']
                measure = {'text': 'Text', 'label': 'Label', 'enum': 'Label', 'boolean': 'Boolean',
                           'integer': 'Integer', 'real': 'Real', 'length': 'LengthMeasure',
                           'area': 'AreaMeasure', 'volume': 'VolumeMeasure'}[kind]
                literal = _s(val) if isinstance(val, str) else ('.T.' if val else '.F.') if kind == 'boolean' else str(val) if kind == 'integer' else _f(val)
                values.append(w.entity('IfcPropertySingleValue', Name=_s(prop),
                                       NominalValue=f'IFC{measure.upper()}({literal})'))
            if values:
                result.append((name, root('IfcPropertySet', ('pset', key, name), Name=_s(name), HasProperties=refs(values))))
        return result

    maps = {}
    for obj in objects:
        group = obj.get('group')
        raw = record.normalize(group.ifc) if group is not None else {'class': obj['class'], 'name': obj['name']}
        messages = record.validate(raw, registry, schema) if group is not None else []
        # These specializations require topology or material usage that a bare
        # class tag cannot supply. Reject rather than invent engineering facts.
        if raw.get('class') in ('IfcBeamStandardCase', 'IfcColumnStandardCase', 'IfcMemberStandardCase',
                   'IfcWallStandardCase', 'IfcSlabStandardCase', 'IfcPlateStandardCase',
                   'IfcWallElementedCase', 'IfcSlabElementedCase', 'IfcOpeningElement',
                   'IfcOpeningStandardCase', 'IfcVoidingFeature', 'IfcProjectionElement', 'IfcSurfaceFeature', 'IfcEarthworksCut'):
            messages.append('Class requires explicit feature or material-usage relationships; use a base class or the openings record')
        # Unsupported classes have a deliberate substitute; malformed records are skipped.
        fatal = [m for m in messages if m != 'class is not supported in ' + schema]
        if messages:
            problems.append({'uid': getattr(group, 'uid', ''), 'name': getattr(group, 'name', obj['name']), 'messages': messages})
        if fatal:
            continue
        r = record.apply_type(raw, registry)
        cls = r['class']
        original = cls
        if cls not in TABLES or schema not in TABLES[cls]['schemas']:
            cls = {'IfcFacility': 'IfcBuilding', 'IfcFacilityPart': 'IfcBuildingStorey'}.get(cls, 'IfcBuildingElementProxy')
            r['object_type'] = original
            r.pop('predefined_type', None)
        spatial = record.role({'class': cls}) == 'spatial'
        if cls == 'IfcFacilityPart':
            cls = 'IfcFacilityPartCommon'
            r['object_type'] = r.get('object_type') or original
        excluded = {o['group_uid'] for o in r.get('openings', []) if o.get('group_uid')}
        if group is not None:
            arrays = merged(world_arrays(group, bases[id(group)], excluded))
            # Appearance needs attributes only, never geometric face objects.
            from core.bim import _untagged_part
            from core.group import iter_placements
            attributes = [attrs for placed, _ in iter_placements(_untagged_part(group, excluded))
                          for attrs in face_attributes(placed.mesh)]
            faces = []
        elif 'arrays' in obj:
            arrays = obj['arrays']()
            attributes = obj['attributes']
            faces = []
        else:
            faces = obj['faces']
            arrays = faces_arrays(faces)
        eg = object_guid(scene, obj)
        attrs = dict(GlobalId=_s(eg), OwnerHistory=owner,
                     Name=_s(raw.get('name') or (group.name if group is not None else obj['name']) or cls),
                     Description=_s(r.get('description', '')), ObjectType=_s(r.get('object_type', '')),
                     ObjectPlacement=ref(placement))
        rep, item = None, None
        if len(arrays.ring_counts):
            if config.get('instancing', False) and group is not None:
                rep = mapped_body(w, group, bases[id(group)], excluded,
                                  body, geometry, maps, axis)
            else:
                rep = array_body(w, arrays, body, geometry)
            item = w.last_shape_item
            attrs['Representation'] = ref(w.add('IFCPRODUCTDEFINITIONSHAPE', '$', '$', refs([rep])))
        available = w.attributes(cls)
        if 'Tag' in available:
            attrs['Tag'] = _s(r.get('tag', ''))
        if 'CompositionType' in available:
            attrs['CompositionType'] = '.ELEMENT.'
        if 'PredefinedType' in available:
            pt = r.get('predefined_type') or 'NOTDEFINED'
            if pt not in predefined_types(cls, schema) or (pt == 'USERDEFINED' and not r.get('object_type')):
                pt = 'NOTDEFINED'
            attrs['PredefinedType'] = '.' + pt + '.'
        if cls == 'IfcFacilityPartCommon':
            attrs['UsageType'] = '.NOTDEFINED.'
        if cls == 'IfcBuildingStorey':
            from PySide6.QtGui import QVector3D
            matrix = _compose(bases[id(group)], group.xform) if group is not None else None
            attrs['Elevation'] = _f(matrix.map(QVector3D()).z() if matrix is not None else 0)
        qname, qentries, _ = class_quantities_arrays(original, arrays) if "arrays" in obj else class_quantities(original, faces)
        dims = {name: value for kind, name, value in qentries}
        if cls in ('IfcDoor', 'IfcWindow'):
            for attr, dim in [('OverallHeight', 'Height'), ('OverallWidth', 'Width')]:
                if dims.get(dim, 0) > 0:
                    attrs[attr] = _f(dims[dim])
        if cls == 'IfcReinforcingBar':
            d = dims.get('NominalDiameter')
            if d:
                attrs.update(NominalDiameter=_f(d), CrossSectionArea=_f(math.pi*d*d/4))
            if dims.get('Length', 0) > 0:
                attrs['BarLength'] = _f(dims['Length'])
        attrs = {k: v for k, v in attrs.items() if k in available}
        node = w.entity(cls, **attrs)
        if "arrays" in obj:
            data = measurements(arrays)
            appearance.apply(r, group, faces, node, eg, rep, item,
                             attributes, data[0] if data is not None else [])
        else:
            appearance.apply(r, group, faces, node, eg, rep, item)
        for index, opening in enumerate(r.get('openings', [])):
            from core.ifc_identity import ensure_guid
            oarrays = recorded_arrays(opening.get('faces', []))
            if opening.get('group_uid'):
                child = next((g for g, _ in _placed_groups(group.children) if g.uid == opening['group_uid']), None)
                if child is not None:
                    oarrays = merged(world_arrays(child, bases[id(child)]))
            if array_quantities(oarrays)[2] is None:
                problems.append({'uid': getattr(group, 'uid', ''), 'name': opening.get('name', ''),
                                 'messages': ['Opening requires a closed face set or a valid closed child group']})
                continue
            # Assign on the stored record, never just on the detached export view.
            if 'openings' not in group.ifc:
                from copy import deepcopy
                group.ifc['openings'] = deepcopy(r['openings'])
            stored = group.ifc['openings'][index]
            if not stored.get('guid'):
                ensure_guid(stored)
                scene.version += 1
            og = stored['guid']
            oa = dict(GlobalId=_s(og), Name=_s(opening.get('name', 'Opening')),
                      ObjectPlacement=ref(placement), PredefinedType='.OPENING.')
            if len(oarrays.ring_counts):
                orep = array_body(w, oarrays, body, geometry)
                oa['Representation'] = ref(w.entity('IfcProductDefinitionShape', Representations=refs([orep])))
            onode = w.entity('IfcOpeningElement', **oa)
            opening_nodes[og] = onode
            relation('IfcRelVoidsElement', (eg, og), RelatingBuildingElement=ref(node), RelatedOpeningElement=ref(onode))
        if r.get('fills'):
            pending_fills.append((eg, node, r['fills']))
        exported.append((obj, node, eg, spatial, cls))
        if group is not None:
            group_nodes[id(group)] = (node, eg, spatial, cls)
        for ps_name, ps in psets(raw.get('psets', {}), eg):
            relation('IfcRelDefinesByProperties', (eg, ps_name), RelatedObjects=refs([node]), RelatingPropertyDefinition=ref(ps))
        manual = dict(r.get('quantities', {}))
        quantities = {name: (kind, value) for kind, name, value in qentries}
        # The record examples use generic Volume/Area; map these to the
        # measured class quantity instead of leaving two conflicting totals.
        for alias, candidates in {
            'Volume': ('GrossVolume', 'NetVolume'),
            'Area': ('NetSideArea', 'GrossArea', 'NetArea'),
            'Mass': ('Weight', 'GrossWeight', 'NetWeight'),
        }.items():
            if alias in manual and alias not in quantities:
                target = next((name for name in candidates if name in quantities), None)
                if target:
                    manual.setdefault(target, manual.pop(alias))
        for name, value in manual.items():
            kind = quantities.get(name, (None,))[0]
            if kind is None and name in ('Height', 'Width', 'Depth', 'Thickness', 'Perimeter', 'Diameter'):
                kind = 'length'
            if kind is None:
                kind = next((k for k in ('volume', 'area', 'weight', 'length') if k in name.lower()), None)
            if kind is None:
                problems.append({'uid': getattr(group, 'uid', ''), 'name': attrs['Name'],
                                 'messages': ['Unknown manual quantity dimension: ' + name]})
                continue
            quantities[name] = (kind, value['value'])
        qids = [w.entity('IfcQuantity' + kind.title(), Name=_s(name),
                         Description=_s('manual') if name in manual else '$',
                         **{kind.title() + 'Value': _f(val)}) for name, (kind, val) in quantities.items() if val >= 0]
        if qids:
            eq = root('IfcElementQuantity', ('quantities', eg), Name=_s(qname), Quantities=refs(qids))
            relation('IfcRelDefinesByProperties', ('quantities', eg), RelatedObjects=refs([node]), RelatingPropertyDefinition=ref(eq))
        for item in raw.get('classifications', []):
            classifications[(item['system'], item['code'])].append(node)
            classification_names.setdefault((item['system'], item['code']), item.get('name', ''))
        if raw.get('type') and TABLES.get(cls, {}).get('domain') != 'group':
            type_members[raw['type']].append(node)
        for key in r.get('systems', []):
            system_members[key].append(node)

    appearance.finish()
    for eg, node, opening in pending_fills:
        if opening in opening_nodes:
            relation('IfcRelFillsElement', (eg, opening), RelatingOpeningElement=ref(opening_nodes[opening]), RelatedBuildingElement=ref(node))
        else:
            problems.append({'uid': eg, 'name': '', 'messages': ['Unknown opening: ' + opening]})
    named_storeys = {}
    named_guids = {}
    aggregates = defaultdict(list)
    containment = defaultdict(list)
    for obj, node, eg, spatial, cls in exported:
        group = obj.get('group') or obj.get('owner')
        ancestor = parents.get(id(group)) if obj.get('group') is not None else group
        found = None
        while ancestor is not None:
            candidate = group_nodes.get(id(ancestor))
            if candidate and (not spatial or candidate[2]):
                found = candidate
                break
            ancestor = parents.get(id(ancestor))
        if spatial:
            parent = found[0] if found else defaults[{'IfcSite': 'site', 'IfcBuilding': 'site',
                    'IfcFacility': 'site', 'IfcBuildingStorey': 'building', 'IfcFacilityPartCommon': 'building'}.get(cls, 'storey')]
            if cls == 'IfcSite' and not found:
                parent = project
            aggregates[parent].append(node)
        elif found and not found[2]:
            aggregates[found[0]].append(node)
        elif TABLES.get(cls, {}).get('domain') == 'group':
            pass
        else:
            parent = found[0] if found else defaults['storey']
            shortcut = (group.ifc or {}).get('storey') if group is not None else None
            if shortcut and (not found or found[3] == 'IfcBuilding'):
                name = shortcut.get('name') if isinstance(shortcut, dict) else shortcut
                building = found[0] if found else defaults['building']
                building_guid = found[1] if found else guid('building')
                key = (building_guid, name)
                if key not in named_storeys:
                    elevation = registry.get('storeys', {}).get(name, {}).get('elevation', shortcut.get('elevation', 0) if isinstance(shortcut, dict) else 0)
                    parent = root('IfcBuildingStorey', ('named-storey', *key), Name=_s(name),
                                  ObjectPlacement=ref(placement), CompositionType='.ELEMENT.', Elevation=_f(elevation))
                    named_storeys[key] = parent
                    named_guids[parent] = guid('named-storey', *key)
                    aggregates[building].append(parent)
                parent = named_storeys[key]
            containment[parent].append(node)
    # Relationship identities use semantic parent GUIDs, not transient STEP ids.
    node_guids = {node: eg for _, node, eg, _, _ in exported}
    node_guids.update({value: guid(key) for key, value in defaults.items()})
    node_guids.update(named_guids)
    node_guids[project] = guid('project')
    for parent, children in aggregates.items():
        relation('IfcRelAggregates', ('children', node_guids[parent]), RelatingObject=ref(parent), RelatedObjects=refs(children))
    for parent, children in containment.items():
        relation('IfcRelContainedInSpatialStructure', (node_guids[parent],), RelatingStructure=ref(parent), RelatedElements=refs(children))

    for key, members in type_members.items():
        data = record.normalize(registry['types'][key])
        cls = TABLES.get(data.get('ifc_class'), {}).get('type_class', {}).get(schema) or 'IfcBuildingElementProxyType'
        if cls.upper() not in SCHEMA_DATA[schema]['orders']:
            cls = 'IfcBuildingElementProxyType'
        if schema == 'IFC4' and cls == 'IfcTransformerType':
            # The published IFC4 ADD2 TC1 schema misspells the type in
            # IfcTransformer's CorrectTypeAssigned rule ("IfcTranformerType"),
            # so a typed transformer can never pass a schema check in IFC4.
            # IFC4X3 fixed it; until then the occurrences stay untyped.
            problems.append({'uid': '', 'name': key, 'messages': [
                'IFC4 cannot type IfcTransformer (schema typo in its WHERE rule); '
                'export with IFC4X3_ADD2 for the type relationship']})
            continue
        attrs = dict(Name=_s(data.get('name', key)), Description=_s(data.get('description', '')),
                     ElementType=_s(data.get('object_type', '')))
        if 'PredefinedType' in w.attributes(cls):
            attrs['PredefinedType'] = '.' + (data.get('predefined_type') or 'NOTDEFINED') + '.'
        if cls in ('IfcDoorType', 'IfcWindowType'):
            attrs.update(ParameterTakesPrecedence='.F.')
            attrs['OperationType' if cls == 'IfcDoorType' else 'PartitioningType'] = '.NOTDEFINED.'
        ps = psets(data.get('psets', {}), 'type:' + key)
        if ps:
            attrs['HasPropertySets'] = refs([node for _, node in ps])
        node = root(cls, ('type', key), **attrs)
        relation('IfcRelDefinesByType', (key,), RelatedObjects=refs(members), RelatingType=ref(node))
        for item in data.get('classifications', []):
            classifications[(item['system'], item['code'])].append(node)
            classification_names.setdefault((item['system'], item['code']), item.get('name', ''))
    for key, members in system_members.items():
        data = registry['systems'][key]
        cls = data.get('ifc_class', 'IfcSystem')
        node = root(cls, ('system', key), Name=_s(data.get('name', key)), Description=_s(data.get('description', '')))
        relation('IfcRelAssignsToGroup', (key,), RelatedObjects=refs(members), RelatingGroup=ref(node))
    sources = {}
    for (system, code), members in classifications.items():
        name = classification_names[(system, code)]
        if system not in sources:
            data = registry['classification_systems'][system]
            sources[system] = w.entity('IfcClassification', Name=_s(data.get('name', system)),
                    Source=_s(data.get('source', '')),
                    **{'Location' if schema == 'IFC4' else 'Specification': _s(data.get('location') or data.get('source', ''))},
                    Edition=_s(data.get('edition', '')), Description=_s(data.get('description', '')))
        node = w.entity('IfcClassificationReference', Identification=_s(code), Name=_s(name), ReferencedSource=ref(sources[system]))
        relation('IfcRelAssociatesClassification', (system, code), RelatedObjects=refs(members), RelatingClassification=ref(node))
    stream.write('ENDSEC;\nEND-ISO-10303-21;\n')
    return ExportReport(len(exported), path, problems, [], linked_skipped)
