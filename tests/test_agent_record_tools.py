# SPDX-License-Identifier: GPL-3.0-or-later
"""Record batches operate on placements and leave shared geometry untouched."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QMatrix4x4
from core.agent_inspection import InspectionTools
from core.agent_records import RecordTools
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from core.history import History


class Agent(RecordTools, InspectionTools):
    pass


@pytest.fixture
def model():
    scene = Scene()
    parent = Group(Mesh(), 'Ride')
    parent.ifc = {'class': 'IfcSpace'}
    mesh = Mesh()
    children = [Group(mesh, 'Car ' + str(i)) for i in range(3)]
    for child in children:
        child.xform = QMatrix4x4()
    parent.children = children
    scene.groups.append(parent)
    agent = Agent()
    agent._viewport = SimpleNamespace(scene=scene, history=History(scene))
    return agent, parent, children


def test_batch_history_and_rejection(model):
    a, parent, children = model
    vp = a._viewport
    ids = [g.uid for g in children]
    serials = [m._mut_serial for m in (vp.scene.mesh, children[0].mesh)]
    revision = vp.scene.mesh.revision
    assert a._tool_set_record(ids, {'class': 'IfcWall'})['applied']
    saved = deepcopy([g.ifc for g in children])
    assert len(vp.history.undo_stack) == 1
    assert vp.scene.mesh.revision > revision
    vp.history.undo()
    assert all(g.ifc is None for g in children)
    vp.history.redo()
    assert [g.ifc for g in children] == saved
    assert serials == [m._mut_serial for m in (vp.scene.mesh, children[0].mesh)]
    rejected = a._tool_set_record(ids, {'predefined_type': 'BAD'})
    assert not rejected['applied'] and all(rejected['problems'].values())
    assert len(vp.history.undo_stack) == 1
    with pytest.raises(ValueError):
        a._tool_set_record(ids + ['missing'], None)
    assert [g.ifc for g in children] == saved
    assert a._tool_set_record(ids, {'predefined_type': 'BAD'}, force=True)['applied']
    assert a._tool_query_record(ids[0])['problems']
    a._tool_untag(ids)
    assert all(g.ifc is None for g in children)


def test_classifications_are_per_target(model):
    a, _, children = model
    ids = [g.uid for g in children]
    a._tool_tag(ids, 'IfcBeam', name='Beam')
    a._tool_add_classification(ids[:1], 'discipline', 'S')
    depth = len(a._viewport.history.undo_stack)
    a._tool_add_classification(ids, 'discipline', 'A')
    assert len(a._viewport.history.undo_stack) == depth + 1
    assert len(children[0].ifc['classifications']) == 2
    assert children[1].ifc['classifications'][0]['name'] == 'Architectural'
    a._tool_remove_classification(ids, 'discipline', 'A')
    assert len(children[0].ifc['classifications']) == 1
    assert children[1].ifc['classifications'] == []
    a._tool_remove_classification(ids, 'discipline')
    assert children[0].ifc['classifications'] == []


def test_registry_vocabulary_and_filters(model):
    a, parent, children = model
    ids = [g.uid for g in children]
    a._tool_set_registry(a._tool_query_registry())
    a._tool_set_type('car', {'ifc_class': 'IfcBeam', 'psets': {'Custom': {'x': 3}}})
    a._tool_set_system('ride', {'ifc_class': 'IfcSystem'})
    a._tool_add_classification_system('client', 'Client')
    a._tool_import_classification_codes('client', 'code,title,parent\nX,Car,\nY,Wheel,X\n')
    a._tool_set_record(ids[:2], {'class': 'IfcBeam', 'type': 'car', 'systems': ['ride']})
    a._tool_add_classification(ids[:2], 'client', 'X')
    view = a._tool_query_record(ids[0])
    assert view['resolved']['psets']['Custom']['x']['value'] == 3
    assert a._tool_query_record(parent.uid)['role'] == 'spatial'
    for method, key in [(a._tool_delete_type, 'car'), (a._tool_delete_system, 'ride'),
                        (a._tool_delete_classification_system, 'client')]:
        assert method(key) == {'applied': False, 'uids': ids[:2]}
    rows = a._tool_query_records(**{'class': 'IfcBeam'}, system='ride', type='car',
        classification_system='client', code='X', name='CAR', limit=1)
    assert rows['total'] == 2 and rows['next_offset'] == 1
    assert rows['rows'][0]['path'] == ['Ride']
    assert rows['totals'] == {'tagged': 3, 'untagged': 1, 'linked': 0, 'by_class': {'IfcSpace': 1, 'IfcBeam': 2}}
    assert a._tool_query_records(untagged=True)['rows'][0]['uid'] == ids[2]
    assert a._tool_query_records(offset=2)['rows'][0]['uid'] == ids[1]
    vocabulary = a._tool_query_vocabulary(**{'class': 'IfcWall'})
    assert vocabulary['codes']['total'] == 0
    assert vocabulary['classification_systems']['client']['code_count'] == 2
    assert vocabulary['classes'][0]['properties']['Status']['members'] == vocabulary['status']
    assert a._tool_query_vocabulary(classification_system='client', limit=1, offset=1)['codes']['rows'][0]['code'] == 'Y'
    assert a._tool_query_vocabulary(search='wheel')['codes']['total'] == 1
    assert a._tool_delete_type('car', force=True)['applied']
    assert a._tool_delete_system('ride', force=True)['applied']
    assert a._tool_delete_classification_system('client', force=True)['applied']
    assert a._tool_query_record(ids[0])['problems']
    detached = a._tool_query_registry()
    detached['types']['oops'] = {}
    assert 'oops' not in a._tool_query_registry()['types']


def test_invalid_csv_and_paging_are_atomic(model):
    a, _, children = model
    before = a._tool_query_registry()
    with pytest.raises(ValueError):
        a._tool_import_classification_codes('discipline', 'code,title\nX,A\nX,B\n')
    assert before == a._tool_query_registry()
    for method in (a._tool_query_records, a._tool_query_vocabulary):
        with pytest.raises(ValueError):
            method(limit=0)
    with pytest.raises(ValueError):
        a._tool_query_vocabulary(schema='invalid')


def test_bridge_record_round_trip(monkeypatch):
    from tests.test_ai_bridge import _ask
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv('INGETRAZO_AI_PORT', '0')
    win = MainWindow()
    bridge = _Bridge(win.viewport)
    try:
        g = Group(Mesh(), 'Agent target')
        win.viewport.scene.groups.append(g)
        bridge.start()
        reply = _ask(bridge, 'tag', {'uids': [g.uid], 'ifc_class': 'IfcWall'})
        assert reply['ok'] and reply['result']['applied']
        assert len(win.viewport.history.undo_stack) == 1
        assert _ask(bridge, 'query_record', {'uid': g.uid})['result']['record']['class'] == 'IfcWall'
        tools = _ask(bridge, 'list_tools')['result']['tools']
        assert not next(t for t in tools if t['name'] == 'set_record')['annotations']['readOnlyHint']
        assert next(t for t in tools if t['name'] == 'query_registry')['annotations']['readOnlyHint']
    finally:
        bridge.stop()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_hundreds_of_placements_and_read_only_queries(model):
    a, parent, children = model
    parent.children.extend(Group(children[0].mesh, 'Extra') for _ in range(400))
    ids = [g.uid for g in parent.children]
    vp = a._viewport
    serial = children[0].mesh._mut_serial
    assert a._tool_set_record(ids, {'class': 'IfcBeam'})['applied']
    assert len(vp.history.undo_stack) == 1
    assert len({g.ifc['guid'] for g in parent.children}) == len(ids)
    version, revision = vp.scene.version, vp.scene.mesh.revision
    assert a._tool_query_records()['next_offset'] == 200
    a._tool_query_record(ids[0])
    a._tool_query_vocabulary()
    a._tool_query_registry()
    assert (vp.scene.version, vp.scene.mesh.revision) == (version, revision)
    assert children[0].mesh._mut_serial == serial
    vp.history.undo()
    assert all(g.ifc is None for g in parent.children)
    vp.history.redo()
    assert all(g.ifc['class'] == 'IfcBeam' for g in parent.children)


def test_forced_malformed_type_remains_readable(model):
    a, _, children = model
    result = a._tool_set_record([children[0].uid], {'class': 'IfcBeam', 'type': []}, force=True)
    assert result['applied'] and result['records'][0]['problems']
    # A broken type reference resolves as "no type": the view stays readable
    # and the problems list is what reports it.
    assert result['records'][0]['resolved']['class'] == 'IfcBeam'
    assert a._tool_set_record([children[0].uid], {'type': None})['applied']


def test_apply_type_tolerates_a_malformed_type_reference():
    """A record pointing at a missing or broken type still resolves, and the
    validator is what reports the problem."""
    from core import record
    registry = {'types': {'broken': 'not an object'}}
    for key in ('missing', 'broken', ['list'], 7):
        view = record.apply_type({'class': 'IfcWall', 'type': key}, registry)
        assert view['class'] == 'IfcWall'
    problems = record.validate({'class': 'IfcWall', 'type': 'missing'}, registry)
    assert any('type' in p.lower() for p in problems)


def test_export_ifc_tool_writes_next_to_the_document(model, tmp_path):
    a, parent, children = model
    ids = [g.uid for g in children]
    a._tool_tag(ids, 'IfcColumn')
    a._viewport.window = lambda: SimpleNamespace(_current_path=tmp_path / 'ride.igz')
    result = a._tool_export_ifc('out/ride', profile=None)
    path = tmp_path / 'out' / 'ride.ifc'
    assert result['path'] == str(path) and path.exists()
    assert result['count'] == 4  # the space and its three columns
    assert result['problems'] == [] and result['ids'] == []
    text = path.read_text(encoding='ascii')
    assert text.count('IFCCOLUMN(') == 3 and "FILE_SCHEMA(('IFC4'))" in text
    with pytest.raises(ValueError):
        a._tool_export_ifc('')


def test_linked_content_is_visible_read_only_and_left_out_of_the_export(model, tmp_path):
    """A facilities file linked into the track: the agent sees it flagged,
    cannot write records into it, and the host export leaves it out unless
    the profile opts in."""
    a, parent, children = model
    linked = Group(Mesh(), 'Facilities')
    linked.ext = {'link': {'path': '/models/facilities.igz'}}
    inner = Group(Mesh(), 'Kiosk')
    inner.ifc = {'class': 'IfcBuildingElementProxy'}
    linked.children = [inner]
    a._viewport.scene.groups.append(linked)
    a._tool_tag([g.uid for g in children], 'IfcColumn')

    rows = {r['uid']: r for r in a._tool_query_tree(depth=5)['rows']}
    assert rows[linked.uid]['linked'] and rows[inner.uid]['link_source'] == '/models/facilities.igz'
    assert not rows[children[0].uid]['linked']

    result = a._tool_query_records()
    assert result['totals'] == {'tagged': 4, 'untagged': 0, 'linked': 2,
                                'by_class': {'IfcSpace': 1, 'IfcColumn': 3}}
    assert {r['uid'] for r in result['rows'] if r['linked']} == {inner.uid}
    assert all(not r['linked'] for r in a._tool_query_records(linked=False)['rows'])
    assert [r['uid'] for r in a._tool_query_records(linked=True)['rows']] == [linked.uid, inner.uid]

    with pytest.raises(ValueError, match='facilities.igz'):
        a._tool_set_record([inner.uid], {'class': 'IfcWall'})
    with pytest.raises(ValueError):
        a._tool_add_classification([children[0].uid, linked.uid], 'discipline', 'A')
    assert inner.ifc == {'class': 'IfcBuildingElementProxy'}

    a._viewport.window = lambda: SimpleNamespace(_current_path=tmp_path / 'track.igz')
    out = a._tool_export_ifc('track.ifc')
    assert out['count'] == 4 and out['linked_skipped'] == 1
    assert 'IFCBUILDINGELEMENTPROXY(' not in (tmp_path / 'track.ifc').read_text()

    a._tool_set_registry({**a._tool_query_registry(), 'export_profiles': {
        'all': {'schema': 'IFC4', 'include_links': True}}})
    out = a._tool_export_ifc('all.ifc', profile='all')
    assert out['count'] == 5 and out['linked_skipped'] == 0
