"""Records survive export, with real schema and IDS consumers when installed."""
from pathlib import Path
import pytest
from PySide6.QtGui import QVector3D, QMatrix4x4
from core.scene import Scene
from core.group import Group
from formats.ifc import save_ifc
from formats.ifc.entities import Builder
from formats.ifc.step import _s


def rich_scene(schema='IFC4'):
    scene = Scene()
    storey = Group(name='Deck')
    storey.ifc = {'class': 'IfcBuildingStorey'}
    storey.xform = QMatrix4x4()
    storey.xform.translate(0, 0, 7)
    assembly = Group(name='Ride')
    assembly.ifc = {'class': 'IfcElementAssembly'}
    transparent = Group()
    wall = Group(name='Enclosure')
    wall.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                        QVector3D(2, 0, 3), QVector3D(0, 0, 3)])
    wall.ifc = {
        'class': 'IfcWall', 'predefined_type': 'USERDEFINED', 'object_type': 'Ride wall',
        'description': 'Surveyed', 'tag': 'W-1', 'type': 'wall', 'systems': ['ride'],
        'classifications': [{'system': 'discipline', 'code': 'A', 'name': 'Architectural'}],
        'psets': {'Pset_WallCommon': {'Status': {'kind': 'enum', 'value': 'EXISTING'}},
                  'Survey': {'Note': "café 😀 \\ survey", 'Count': 3, 'Checked': True,
                             'Offset': {'kind': 'length', 'value': 0.2}}},
        'quantities': {'NetSideArea': {'value': 8, 'source': 'manual'}}}
    storey.children = [assembly]
    assembly.children = [transparent]
    transparent.children = [wall]
    scene.groups.append(storey)
    scene.plugin_data['bim_registry'] = {
        'classification_systems': {'discipline': {'name': 'Discipline', 'edition': '2026', 'source': 'Survey'}},
        'types': {'wall': {'ifc_class': 'IfcWall', 'name': 'Wall type', 'predefined_type': 'STANDARD',
                          'psets': {'Pset_WallCommon': {'Status': 'NEW', 'IsExternal': True}},
                          'classifications': [{'system': 'discipline', 'code': 'A', 'name': 'Architectural'}]}},
        'systems': {'ride': {'ifc_class': 'IfcSystem', 'name': 'Ride'}, 'unused': {'name': 'Unused'}},
        'project': {'author': 'Surveyor', 'organization': 'Owner'},
        'export_profiles': {'handover': {'schema': schema, 'view': 'ReferenceView'}}}
    return scene, wall


@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
def test_record_round_trip(tmp_path, schema):
    ifc = pytest.importorskip('ifcopenshell')
    import ifcopenshell.validate
    import ifcopenshell.util.element
    scene, wall = rich_scene(schema)
    path = tmp_path / 'ride.ifc'
    report = save_ifc(scene, path, profile='handover')
    assert report.count == 3
    assert not report.problems
    model = ifc.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert not logger.statements
    element = model.by_type('IfcWall')[0]
    assert element.Name == 'Enclosure'
    assert element.Tag == 'W-1'
    assert element.ObjectType == 'Ride wall'
    assert element.PredefinedType == 'USERDEFINED'
    assert element.Description == 'Surveyed'
    psets = ifcopenshell.util.element.get_psets(element)
    assert psets['Pset_WallCommon']['Status'] == 'EXISTING'
    assert psets['Pset_WallCommon']['IsExternal'] is True
    assert psets['Survey']['Note'] == "café 😀 \\ survey"
    assert psets['Qto_WallBaseQuantities']['NetSideArea'] == 8
    assert next(q for q in model.by_type('IfcQuantityArea') if q.Name == 'NetSideArea').Description == 'manual'
    assert len(model.by_type('IfcSystem')) == 1
    assert len(model.by_type('IfcClassificationReference')) == 1
    deck = next(s for s in model.by_type('IfcBuildingStorey') if s.Name == 'Deck')
    assert deck.Elevation == 7
    assert element.Decomposes[0].RelatingObject.is_a('IfcElementAssembly')
    assert ifcopenshell.util.element.get_container(element) == deck
    ids = sorted(e.GlobalId for e in model.by_type('IfcRoot'))
    save_ifc(scene, path, profile='handover')
    assert ids == sorted(e.GlobalId for e in ifc.open(str(path)).by_type('IfcRoot'))


def test_attribute_counts_are_checked():
    with pytest.raises(ValueError):
        Builder('IFC4').add('IfcWall', '$')


def test_invalid_record_is_reported(tmp_path):
    scene, wall = rich_scene()
    wall.ifc['object_type'] = ''
    report = save_ifc(scene, tmp_path / 'invalid.ifc')
    assert report.count == 2
    assert any('USERDEFINED' in m for p in report.problems for m in p['messages'])


@pytest.mark.parametrize('passes', [True, False])
def test_ids_check(tmp_path, passes):
    pytest.importorskip('ifctester')
    scene, wall = rich_scene()
    scene.plugin_data['bim_registry']['export_profiles']['handover']['ids_files'] = [
        str(Path(__file__).parent / 'fixtures' / 'wall-status.ids')]
    if not passes:
        wall.ifc.pop('classifications')
        scene.plugin_data['bim_registry']['types']['wall'].pop('classifications')
    report = save_ifc(scene, tmp_path / 'ids.ifc', profile='handover')
    assert report.ids[0]['status'] == 'checked'
    spec = report.ids[0]['specifications'][0]
    assert spec['status'] == passes
    assert spec['passed'] == int(passes)
    assert spec['failed'] == int(not passes)
    assert (tmp_path / 'ids.ids-report.json').exists()


@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
def test_all_curated_occurrences_validate(tmp_path, schema):
    ifc = pytest.importorskip('ifcopenshell')
    import ifcopenshell.validate
    from core.ifc_tables import IFC_CLASSES
    scene = Scene()
    for cls in IFC_CLASSES:
        group = Group(name=cls)
        group.ifc = {'class': cls}
        scene.groups.append(group)
    scene.plugin_data['bim_registry'] = {'export_profiles': {'test': {'schema': schema}}}
    path = tmp_path / 'classes.ifc'
    save_ifc(scene, path, profile='test')
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(str(path), logger, express_rules=True)
    assert not logger.statements


def test_casita_and_legacy_validate_with_express_rules(tmp_path):
    ifc = pytest.importorskip('ifcopenshell')
    import ifcopenshell.validate
    from tests.test_ifc_bridge import _extrude, _Vp, V
    from core.bim import tag_faces, next_object_id
    scene = Scene()
    vp = _Vp(scene)
    for cls, x, width, depth, height in [
        ('IfcWall', 0, 4, .15, 2.6), ('IfcWall', 5, 4, .15, 2.6),
        ('IfcSlab', 10, 4, 3, .2), ('IfcColumn', 15, .25, .25, 3),
        ('IfcPile', 24, .3, .3, 8)]:
        faces = _extrude(scene, vp, [V(x, 0), V(x+width, 0),
                                    V(x+width, depth), V(x, depth)], height)
        tag_faces(faces, cls, cls, next_object_id(scene))
    door = scene.mesh.add_face([V(30, 0, 0), V(30.9, 0, 0), V(30.9, 0, 2.1), V(30, 0, 2.1)])
    tag_faces([door], 'IfcDoor', 'Door', next_object_id(scene))
    path = tmp_path / 'casita.ifc'
    assert save_ifc(scene, path) == 6
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(str(path), logger, express_rules=True)
    assert not logger.statements


@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
def test_curated_types_validate(tmp_path, schema):
    pytest.importorskip('ifcopenshell')
    import ifcopenshell.validate
    from core.ifc_tables import IFC_CLASSES
    from core.record import role
    scene = Scene()
    types = {}
    for cls in IFC_CLASSES:
        if role({'class': cls}) == 'spatial':
            continue
        group = Group(name=cls)
        group.ifc = {'class': cls, 'type': cls}
        types[cls] = {'ifc_class': cls, 'name': cls}
        scene.groups.append(group)
    scene.plugin_data['bim_registry'] = {
        'types': types, 'export_profiles': {'test': {'schema': schema}}}
    path = tmp_path / 'types.ifc'
    save_ifc(scene, path, profile='test')
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(str(path), logger, express_rules=True)
    assert not logger.statements


def test_generic_manual_area_replaces_the_measured_value(tmp_path):
    ifc = pytest.importorskip('ifcopenshell')
    scene, wall = rich_scene()
    wall.ifc['quantities'] = {'Area': {'value': 12, 'source': 'manual'}}
    path = tmp_path / 'manual.ifc'
    save_ifc(scene, path)
    model = ifc.open(str(path))
    values = {q.Name: q for q in model.by_type('IfcQuantityArea')}
    assert 'Area' not in values
    assert values['NetSideArea'].AreaValue == 12
    assert values['NetSideArea'].Description == 'manual'
