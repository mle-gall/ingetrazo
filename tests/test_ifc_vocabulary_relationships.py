"""Schema facts and user-owned metadata must survive a real IFC consumer."""
import pytest
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.group import Group
from core.materials import Material
from core.layers import Layer
from core.mesh import Mesh
from core.bim import face_set_volume
from core import record, bim_registry
from formats.ifc import save_ifc


def cube(offset=0):
    points = [(offset+x, offset+y, offset+z) for x,y,z in
              [(0,0,0),(2,0,0),(2,2,0),(0,2,0),(0,0,2),(2,0,2),(2,2,2),(0,2,2)]]
    return [{'outer': [points[i] for i in loop]} for loop in
            [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]


def mesh_at(offset):
    mesh = Mesh()
    for face in cube(offset):
        mesh.add_face([QVector3D(*p) for p in face['outer']])
    return mesh


def test_volume_far_from_origin():
    near, far = mesh_at(0), mesh_at(10000)
    assert face_set_volume(near.faces) == pytest.approx(8)
    assert face_set_volume(far.faces) == pytest.approx(face_set_volume(near.faces))


def test_runtime_library(tmp_path):
    xml = tmp_path / 'synthetic.xml'
    xml.write_text('<PropertySetDef><Name>Pset_Test</Name><ApplicableClasses><ClassName>IfcWall</ClassName></ApplicableClasses><PropertyDefs><PropertyDef><Name>State</Name><PropertyType><TypePropertyEnumeratedValue><EnumList name="Test"><EnumItem>READY</EnumItem></EnumList></TypePropertyEnumeratedValue></PropertyType></PropertyDef></PropertyDefs></PropertySetDef>')
    registry = {'pset_library': {'path': str(tmp_path)}}
    r = {'class': 'IfcWall', 'psets': {'Pset_Test': {'State': 'READY'}}}
    assert not record.validate(r, registry)
    r['psets']['Pset_Test']['State'] = 'BAD'
    assert any('enumeration' in e for e in record.validate(r, registry))
    r['psets']['Pset_Test'] = {'Unknown': 1}
    assert any('unknown property' in e for e in record.validate(r, registry))


def test_tag_sets():
    registry = {'tag_sets': {'ride': {'name': 'Ride', 'default': True, 'classes': [{'class': 'IfcBeam'}]}}}
    assert not bim_registry.validate(registry)
    assert bim_registry.ordered_classes(registry)[0] == 'IfcBeam'
    registry['tag_sets']['ride']['classes'][0]['class'] = 'Unknown'
    assert bim_registry.validate(registry)


@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
def test_relationships_round_trip(tmp_path, schema):
    ifc = pytest.importorskip('ifcopenshell')
    import ifcopenshell.validate
    scene = Scene()
    wall = Group(mesh_at(0), 'Wall')
    wall.layer = 'Structure'
    wall.ifc = {'class': 'IfcWall', 'material': {'name': 'Concrete', 'layers': [{'name': 'Concrete', 'thickness': .2}]},
                'storey': 'Deck', 'openings': [{'name': 'Door void', 'faces': cube()}]}
    scene.groups.append(wall)
    scene.materials['Concrete'] = Material('Concrete', color=(.2,.3,.4), opacity=.8)
    scene.layers.append(Layer('Structure'))
    scene.plugin_data['bim_registry'] = {'storeys': {'Deck': {'elevation': 7}}, 'export_profiles': {'test': {'schema': schema}}}
    path = tmp_path / 'relationships.ifc'
    assert not save_ifc(scene, path, profile='test').problems
    door = Group(name='Door')
    door.ifc = {'class': 'IfcDoor', 'fills': wall.ifc['openings'][0]['guid']}
    scene.groups.append(door)
    save_ifc(scene, path, profile='test')
    model = ifc.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert not logger.statements
    for cls in ('IfcMaterial', 'IfcSurfaceStyle', 'IfcPresentationLayerAssignment', 'IfcRelVoidsElement', 'IfcRelFillsElement'):
        assert len(model.by_type(cls)) == 1
    assert next(s for s in model.by_type('IfcBuildingStorey') if s.Name == 'Deck').Elevation == 7
    assert model.by_type('IfcSurfaceStyleRendering')[0].Transparency == pytest.approx(.2)
    ids = sorted(e.GlobalId for e in model.by_type('IfcRoot'))
    save_ifc(scene, path, profile='test')
    assert ids == sorted(e.GlobalId for e in ifc.open(str(path)).by_type('IfcRoot'))


@pytest.mark.parametrize('schema,count', [('IFC4', 130), ('IFC4X3_ADD2', 150)])
def test_generated_concrete_elements(schema, count):
    ifc = pytest.importorskip('ifcopenshell')
    from core.ifc_tables_data import SCHEMA_DATA
    root = ifc.ifcopenshell_wrapper.schema_by_name(schema).declaration_by_name('IfcElement')
    def concrete(entity):
        result = set() if entity.is_abstract() else {entity.name()}
        for child in entity.subtypes():
            result.update(concrete(child))
        return result
    names = concrete(root)
    assert len(names) == count
    assert names <= SCHEMA_DATA[schema]['classes'].keys()


def test_child_opening_and_material_fallback(tmp_path):
    ifc = pytest.importorskip('ifcopenshell')
    scene = Scene()
    wall = Group(mesh_at(0), 'Wall')
    child = Group(mesh_at(4), 'Void')
    wall.children.append(child)
    for face in wall.mesh.faces:
        face.attrs['mat'] = 'Paint'
    scene.materials['Paint'] = Material('Paint', color=(1,0,0))
    wall.ifc = {'class': 'IfcWall', 'openings': [{'group_uid': child.uid}]}
    scene.groups.append(wall)
    path = tmp_path / 'child.ifc'
    result = save_ifc(scene, path)
    assert not result.problems
    model = ifc.open(str(path))
    assert model.by_type('IfcMaterial')[0].Name == 'Paint'
    assert len(model.by_type('IfcRelVoidsElement')) == 1
    assert len(model.by_type('IfcFacetedBrep')) == 2
    assert len(model.by_type('IfcWall')[0].Representation.Representations[0].Items[0].Outer.CfsFaces) == 6


@pytest.mark.parametrize('patch', [
    {'material': {'name': 'x', 'layers': [{'name': 'x', 'thickness': -1}]}},
    {'openings': [{'faces': [{'outer': [[0,0,0]], 'holes': None}]}]},
    {'openings': [{'guid': 'bad'}]}, {'fills': 'bad'}, {'storey': {'name': 'x', 'elevation': float('nan')}},
])
def test_malformed_relationship_records(patch):
    assert record.validate({'class': 'IfcWall', **patch}, {})


def test_copied_openings_get_new_identity_and_internal_references():
    from core.group import copy_group
    from core.ifc_identity import ensure_guid
    host = Group(name='Host')
    void = Group(mesh_at(0), 'Void')
    door = Group(name='Door')
    opening = {'group_uid': void.uid}
    old_guid = ensure_guid(opening)
    host.ifc = {'class': 'IfcWall', 'openings': [opening]}
    door.ifc = {'class': 'IfcDoor', 'fills': old_guid}
    host.children = [door, void]
    copied = copy_group(host)
    copied_opening = copied.ifc['openings'][0]
    assert copied_opening['guid'] != old_guid
    assert copied.children[0].ifc['fills'] == copied_opening['guid']
    assert copied_opening['group_uid'] == copied.children[1].uid
    assert host.ifc['openings'][0]['guid'] == old_guid


def test_quantity_library_and_cache_refresh(tmp_path):
    from core.pset_library import load
    path = tmp_path / 'qto.xml'
    path.write_text('<QtoSetDef><Name>Qto_Test</Name><QtoDefs><QtoDef><Name>Length</Name><QtoType>Q_LENGTH</QtoType></QtoDef></QtoDefs></QtoSetDef>')
    assert load(tmp_path)['Qto_Test']['properties']['Length']['kind'] == 'length'
    path.write_text(path.read_text().replace('Length', 'Volume').replace('Q_LENGTH', 'Q_VOLUME'))
    assert load(tmp_path)['Qto_Test']['properties']['Volume']['kind'] == 'volume'
