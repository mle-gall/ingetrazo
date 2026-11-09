"""Phase 1 filing owns projections on placements, even with shared geometry."""
from copy import deepcopy
from pathlib import Path

import pytest
from core import bim_registry, structure as st
from core.group import Group
from core.history import History
from core.layers import Layer
from core.mesh import Mesh
from core.scene import Scene


def node(name, parent=None, order=0, **recipe):
    return dict(name=name, parent=parent, order=order, recipe=recipe)


def model():
    scene = Scene()
    registry = bim_registry.seed_defaults()
    registry['systems'] = {s: dict(ifc_class='IfcSystem') for s in ('ride', 'track')}
    registry['structure'] = {'nodes': {
        'ride': node('Ride', systems=['ride'], psets={'Survey': {'A': 1, 'B': 1}}),
        'track': node('Track', 'ride', systems=['ride', 'track']),
        'sections': node('Sections', 'track', tag='Track Sections', **{
            'class': 'IfcMember', 'classifications': [{'system': 'discipline', 'code': 'S'}],
            'psets': {'Survey': {'B': 2}}}),
        'ref': node('Reference', 'ride', 1, **{'class': None})}}
    scene.plugin_data['bim_registry'] = registry
    scene.groups = [Group(Mesh(), 'Section'), Group(Mesh(), 'Survey point')]
    return scene, registry, *scene.groups


def test_resolve_file_undo_redo():
    scene, r, g, other = model()
    assert st.path(r, 'sections') == ['Ride', 'Track', 'Sections']
    assert st.tree(r)['ride'] == ['track', 'ref']
    recipe = st.resolve(r, 'sections')
    assert recipe['folder'] == ['Ride', 'Track']
    assert recipe['systems'] == ['ride', 'track']
    assert recipe['psets'] == {'Survey': {'A': 1, 'B': 2}}
    r['structure']['nodes']['ride']['recipe']['classifications'] = recipe['classifications']
    assert len(st.resolve(r, 'sections')['classifications']) == 1
    g.ext = {'other': {'value': 7}}
    h = History(scene)
    versions = scene.version, g.mesh._mut_serial, scene.mesh._mut_serial
    cmd = st.file(scene, [g.uid], 'sections')
    assert g.ext == {'other': {'value': 7}} and not scene.layer_folders
    h.execute(cmd)
    assert len(h.undo_stack) == 1
    assert st.members(scene, 'ride') == [g.uid] and not st.members(scene, 'ride', False)
    assert scene.folder_parents == {'Track': 'Ride'}
    assert scene.layer('Track Sections').folder == 'Track'
    assert st.node_of(g) == 'sections' and g.layer == 'Track Sections'
    saved = deepcopy(g.ifc)
    assert saved['class'] == 'IfcMember' and saved['classifications'][0]['name'] == 'Structural'
    assert other.ifc is None and scene.version > versions[0]
    assert versions[1:] == (g.mesh._mut_serial, scene.mesh._mut_serial)
    h.undo()
    assert g.ext == {'other': {'value': 7}} and g.ifc is None and g.layer is None
    assert not scene.layer_folders and not scene.layer_folder_uids and not scene.folder_parents
    assert scene.layer('Track Sections') is None
    h.redo()
    assert g.ifc == saved
    h.execute(st.unfile(scene, [g.uid]))
    assert g.ext == {'other': {'value': 7}} and g.ifc == saved and g.layer == 'Track Sections'


def test_ownership_resync_and_refusals():
    scene, r, g, other = model()
    g.ifc = {'class': 'IfcWall', 'name': 'Field name', 'description': 'Surveyed', 'tag': 'M6',
             'custom': 123, 'psets': {'Survey': {'B': {'kind': 'integer', 'value': 99}}},
             'quantities': {'Count': {'value': 1, 'source': 'manual'}},
             'classifications': [{'system': 'client', 'code': 'C', 'name': 'C'},
                                 {'system': 'discipline', 'code': 'M'}]}
    prior = deepcopy(g.ifc)
    recipe = r['structure']['nodes']['sections']['recipe']
    recipe['classes_allowed'] = ['IfcMember', 'IfcColumn']
    with pytest.raises(ValueError, match='classes_allowed'):
        st.file(scene, [other.uid, g.uid], 'sections')
    assert other.ext is None and not scene.layer_folders
    g.ifc['class'] = 'IfcColumn'
    st.file(scene, [g.uid], 'sections').do(scene)
    guid = g.ifc['guid']
    assert g.ifc['class'] == 'IfcColumn'
    recipe.update(object_type='Updated', classifications=[dict(system='discipline', code='A')])
    g.ifc['psets']['Pset_ColumnCommon'] = {'Status': {'kind': 'enum', 'value': 'EXISTING'}}
    cmd, report = st.resync(scene, ['ride'])
    assert report == {g.uid: ['object_type', 'classifications']}
    cmd.do(scene)
    assert g.ifc['classifications'][0] == prior['classifications'][0]
    assert g.ifc['classifications'][1]['code'] == 'A'
    assert g.ifc['guid'] == guid and g.ifc['object_type'] == 'Updated'
    for field in ('name', 'tag', 'description', 'quantities', 'custom'):
        assert g.ifc[field] == prior[field]
    assert g.ifc['psets']['Survey']['B']['value'] == 99
    assert g.ifc['psets']['Pset_ColumnCommon']['Status']['value'] == 'EXISTING'
    assert st.resync(scene)[1] == {}
    other.children = [Group(name='Linked child')]
    other.ext = {'link': {'path': 'supplier.igz'}}
    for target in (other, other.children[0]):
        with pytest.raises(ValueError, match='Linked'):
            st.file(scene, [g.uid, target.uid], 'sections')
    g.ifc['class'] = 'IfcWall'
    assert st.unsorted(scene) == [g.uid]


def test_null_class_and_ids_completeness():
    scene, r, g, other = model()
    existing = Group(name='Recorded reference')
    existing.ifc = {'class': 'IfcBeam'}
    scene.groups.append(existing)
    assert len(st.unsorted(scene)) == 3
    st.file(scene, [other.uid, existing.uid], 'ref').do(scene)
    assert other.ifc is None and existing.ifc == {'class': 'IfcBeam'}
    assert st.unsorted(scene) == [g.uid, existing.uid]
    r['structure']['nodes']['sections']['recipe']['class'] = 'IfcWall'
    st.file(scene, [g.uid], 'sections').do(scene)
    r['export_profiles']['handover'] = dict(schema='IFC4', ids_files=[
        str(Path(__file__).parent / 'fixtures/wall-status.ids')])
    stats = st.completeness(scene, r)
    assert stats['ride']['members'] == 3 and stats['ride']['without_record'] == 1
    assert stats['ride']['missing_status'] == 2
    hits = stats['sections']['ids_hits']
    assert [(h['uid'], h['facet'], h['status']) for h in hits] == [(g.uid, 'property', 'failed')]


def test_bootstrap_threshold_conflicts_and_exact_undo():
    scene, r, g, other = model()
    scene.layer_folders = ['Ride', 'Track']
    scene.folder_parents = {'Track': 'Ride'}
    scene.layers.extend([Layer('Rails', folder='Track'), Layer('VIS', folder='Ride'), Layer('_To review')])
    g.layer = other.layer = 'Rails'
    g.ifc = {'class': 'IfcMember'}
    bolt = Group(name='Recorded bolt')
    bolt.layer, bolt.ifc = 'VIS', {'class': 'IfcMechanicalFastener'}
    scene.groups.append(bolt)
    for _ in range(2):
        screw = Group(name='Screw')
        screw.layer = 'VIS'
        scene.groups.append(screw)
    version = scene.version
    p = st.bootstrap(scene, r)
    assert not scene.layer_folder_uids and scene.version == version and st.node_of(g) is None
    nodes = p['structure']['nodes']
    keys = {v['name']: k for k, v in nodes.items()}
    assert st.path({'structure': p['structure']}, keys['Rails']) == ['Ride', 'Track', 'Rails']
    assert nodes[keys['VIS']]['recipe']['class'] is None
    assert nodes[keys['Rails']]['recipe']['class'] == 'IfcMember'
    assert p['conflicts'] == [
        dict(node=keys['Rails'], reason='would newly classify', count=1),
        dict(node=keys['VIS'], reason='recorded under null class',
             placements=[{'uid': bolt.uid, 'class': 'IfcMechanicalFastener'}]),
        dict(node=keys['_To review'], reason='review layer', count=0, placements=[])]
    before = deepcopy(r)
    h = History(scene)
    h.execute(st.apply_bootstrap(scene, p))
    assert len(h.undo_stack) == 1 and other.ifc['class'] == 'IfcMember'
    assert st.node_of(bolt) == keys['VIS'] and bolt.ifc == {'class': 'IfcMechanicalFastener'}
    h.undo()
    assert bim_registry.get(scene) == before and other.ifc is None and st.node_of(bolt) is None


@pytest.mark.parametrize('field,value', [
    ('class', 'NotAClass'), ('classes_allowed', ['IfcWall']), ('classifications', [{}]),
    ('classifications', [dict(system='discipline', code='bad')]), ('systems', ['missing']),
    ('type', 'missing'), ('psets', []), ('predefined_type', 'BAD')])
def test_registry_checks_inherited_vocabulary(field, value):
    _, r, *_ = model()
    r['structure']['nodes']['sections']['recipe'][field] = value
    assert bim_registry.validate(r)


def test_registry_tree_and_unknown_fields():
    scene, r, *_ = model()
    r['structure']['future'] = {'v': 123}
    r['structure']['nodes']['sections']['future'] = 5
    assert not bim_registry.validate(r)
    for edit in ({'parent': 'sections'}, {'parent': []}, {'order': True}, {'name': ''}):
        candidate = deepcopy(r)
        candidate['structure']['nodes']['ride'].update(edit)
        assert bim_registry.validate(candidate)
    r['structure']['active'] = 'gone'
    assert bim_registry.validate(r)


def test_shared_structure_and_local_membership(tmp_path):
    from core import project
    from formats import igz
    scene, r, g, _ = model()
    project.create(scene, tmp_path / 'shared.igzproj')
    sibling = Scene()
    project.attach(sibling, tmp_path / 'shared.igzproj')
    st.file(scene, [g.uid], 'sections').do(scene)
    igz.save_scene(scene, tmp_path / 'ride.igz')
    restored = Scene()
    igz.load_into(restored, tmp_path / 'ride.igz')
    assert bim_registry.get(sibling)['structure'] == r['structure']
    assert st.members(restored, 'track') == [g.uid]
    assert st.members(sibling, 'track') == []


def test_projection_preserves_legacy_shorthand_and_redo_layer_identity():
    scene, _, g, _ = model()
    scene.layer_folders = ['Empty legacy folder']
    g.ifc = {'class': 'IfcMember', 'quantities': {'Volume': 9},
             'psets': {'Survey': {'B': 4}}}
    h = History(scene)
    h.execute(st.file(scene, [g.uid], 'sections'))
    assert g.ifc['quantities'] == {'Volume': 9}
    assert g.ifc['psets']['Survey']['B'] == 4
    uid = scene.layer('Track Sections').uid
    folder_uid = scene.layer_folder_uids['Track']
    h.undo()
    assert scene.layer_folder_uids == {} and scene.layer_folders == ['Empty legacy folder']
    h.redo()
    assert scene.layer('Track Sections').uid == uid and scene.layer_folder_uids['Track'] == folder_uid


def test_link_mount_uses_authored_source_tree(tmp_path):
    from core import links
    from formats import igz
    source, _, g, _ = model()
    st.file(source, [g.uid], 'sections').do(source)
    doc = tmp_path / 'supplier.igz'
    igz.save_scene(source, doc)
    host = Scene()
    mount = links.make_link(host, doc)
    host.groups.append(mount)
    proposal = st.bootstrap(host, bim_registry.get(host))
    nodes = proposal['structure']['nodes']
    assert nodes['link:supplier/ride']['parent'] == 'link:supplier'
    assert nodes['link:supplier/sections']['name'] == 'Sections'
    assert proposal['filing'] == {}
    st.apply_bootstrap(host, proposal).do(host)
    assert st.members(host, 'link:supplier/sections') == [mount.children[0].uid]
    with pytest.raises(ValueError, match='Linked'):
        st.file(host, [mount.children[0].uid], 'link:supplier/sections')


def test_move_occupied_subtree_reprojects_folders_undoably():
    scene, r, g, _ = model()
    st.file(scene, [g.uid], 'sections').do(scene)
    r['structure']['nodes']['ride']['name'] = 'Coaster'
    cmd, report = st.resync(scene)
    assert report == {g.uid: ['folder']}
    cmd.do(scene)
    assert scene.folder_parents['Track'] == 'Coaster'
    cmd.undo(scene)
    assert scene.folder_parents['Track'] == 'Ride'
    assert 'Coaster' not in scene.layer_folders


def test_registry_replacement_cannot_orphan_local_members():
    from core.history import SetRegistryCommand
    scene, r, g, _ = model()
    st.file(scene, [g.uid], 'sections').do(scene)
    candidate = deepcopy(r)
    del candidate['structure']['nodes']['sections']
    h = History(scene)
    h.execute(SetRegistryCommand(candidate))
    assert 'occupied node' in h.last_rejected and not h.undo_stack
    assert st.members(scene, 'sections') == [g.uid]
