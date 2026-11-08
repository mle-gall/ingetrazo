# SPDX-License-Identifier: GPL-3.0-or-later
from copy import deepcopy
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from core import record, bim_registry
from core.group import Group, copy_group
from core.mesh import Mesh
from core.scene import Scene
from core.history import (History, SetRecordCommand, TagGroupsCommand,
                          UntagGroupsCommand, SetRegistryCommand, SetFaceTagsCommand)
from core.ifc_identity import ensure_guid
from formats import igz


def full_record():
    r = {'v': 1, 'class': 'IfcWall', 'predefined_type': 'USERDEFINED',
         'object_type': 'Ride enclosure', 'name': 'Wall', 'tag': 'C-12',
         'description': 'Existing enclosure', 'type': 'wall', 'systems': ['ride'],
         'classifications': [{'system': 'discipline', 'code': 'A', 'name': 'Architectural'}],
         'psets': {'Pset_WallCommon': {'Status': {'kind': 'enum', 'value': 'EXISTING'}},
                   'Custom': {k: {'kind': k, 'value': v} for k, v in
                              [('text', 'a'), ('boolean', True), ('integer', 2), ('real', 2.5),
                               ('length', 1.0), ('area', 2.0), ('volume', 3.0), ('label', 'X')]}},
         'quantities': {'Volume': {'value': 1.2, 'source': 'manual'}},
         'future': {'nested': [1, True, None]}}
    ensure_guid(r)
    return r


def registry():
    r = bim_registry.seed_defaults()
    r['types']['wall'] = {'name': 'Wall type', 'ifc_class': 'IfcWall'}
    r['systems']['ride'] = {'name': 'Ride', 'ifc_class': 'IfcSystem'}
    return r


def test_normalize_and_resolve():
    old = {'class': 'IfcWall', 'name': 'Legacy'}
    assert record.normalize(old) == old
    r = full_record()
    assert not record.validate(r, registry())
    assert record.normalize(r) == r
    r['psets']['Custom']['short'] = False
    assert record.normalize(r)['psets']['Custom']['short'] == {'kind': 'boolean', 'value': False}
    reg = registry()
    reg['types']['wall']['psets'] = {'Custom': {'inherited': 42, 'text': 'default'}}
    resolved = record.apply_type(r, reg)
    assert resolved['psets']['Custom']['inherited']['value'] == 42
    assert resolved['psets']['Custom']['text']['value'] == 'a'
    assert 'inherited' not in r['psets']['Custom']


@pytest.mark.parametrize('patch', [
    {'predefined_type': 'USERDEFINED', 'object_type': ''}, {'predefined_type': 'BAD'},
    {'systems': ['missing']}, {'type': 'missing'}, {'classifications': [{'system': 'missing'}]},
    {'psets': {'Custom': {'x': {'kind': 'boolean', 'value': 1}}}},
    {'quantities': {'Volume': {'value': 1, 'source': 'measured'}}}, {'guid': 'bad'},
])
def test_validation(patch):
    assert record.validate({**full_record(), **patch}, registry())


@pytest.mark.parametrize('cls,role', [('IfcSpace', 'spatial'), ('IfcFacility', 'spatial'),
    ('IfcElementAssembly', 'assembly'), ('IfcBuildingElementPart', 'part'), ('IfcWall', 'element')])
def test_role(cls, role):
    assert record.role({'class': cls}) == role


@pytest.mark.parametrize('kind', ['set', 'tag', 'untag', 'registry'])
def test_commands_preserve_geometry(kind):
    scene = Scene(); group = Group(Mesh(), 'Object'); scene.groups.append(group)
    group.ifc = full_record(); before = deepcopy(group.ifc)
    history = History(scene)
    command = {'set': lambda: SetRecordCommand([group], {'name': 'Edited'}),
               'tag': lambda: TagGroupsCommand([group], 'IfcBeam', 'Beam'),
               'untag': lambda: UntagGroupsCommand([group]),
               'registry': lambda: SetRegistryCommand(registry())}[kind]()
    meshes = [scene.mesh, group.mesh]
    serials = [(m._mut_serial, getattr(m, '_winding_rev', 0)) for m in meshes]
    rev, version = scene.mesh.revision, scene.version
    history.execute(command)
    after = deepcopy(group.ifc)
    assert history.changes_since(0)['changes']
    assert scene.version > version and scene.mesh.revision > rev
    history.undo()
    assert group.ifc == before
    if kind == 'registry': assert 'bim_registry' not in scene.plugin_data
    history.redo()
    assert group.ifc == after
    assert [(m._mut_serial, getattr(m, '_winding_rev', 0)) for m in meshes] == serials


@pytest.mark.parametrize("component", [False, True])
def test_round_trip_and_copy(tmp_path, component):
    scene = Scene(); group = Group(Mesh(), 'Object'); scene.groups.append(group)
    group.component = component
    if component:
        from PySide6.QtGui import QMatrix4x4
        group.xform = QMatrix4x4()
    group.ifc = full_record(); scene.plugin_data['bim_registry'] = registry()
    copied = copy_group(group)
    assert (copied.mesh is group.mesh) == component
    ensure_guid(copied.ifc)
    assert copied.ifc['guid'] != group.ifc['guid']
    assert {k:v for k,v in copied.ifc.items() if k != 'guid'} == {k:v for k,v in group.ifc.items() if k != 'guid'}
    copied.ifc['psets']['Custom']['text']['value'] = 'changed'
    assert group.ifc['psets']['Custom']['text']['value'] == 'a'
    path = tmp_path / 'records.igz'; igz.save_scene(scene, path)
    loaded = Scene(); igz.load_into(loaded, path)
    assert loaded.groups[0].ifc == group.ifc
    assert loaded.plugin_data['bim_registry'] == scene.plugin_data['bim_registry']
    assert record.describe(loaded.groups[0])['record'] == group.ifc


def test_csv_atomic():
    reg = registry()
    imported = bim_registry.import_codes_csv(reg, 'uniclass2015', 'code,title,parent\nX,"A, B",\nY,Child,X\n')
    assert imported['classification_systems']['uniclass2015']['codes']['Y']['parent'] == 'X'
    assert 'codes' not in reg['classification_systems']['uniclass2015']
    with pytest.raises(ValueError):
        bim_registry.import_codes_csv(reg, 'uniclass2015', 'code,title\nX,A\nX,B\n')


def test_panel_tag_untag_multiselect():
    from views.tray import BimPanel
    app = QApplication.instance() or QApplication([])
    scene = Scene(); groups = [Group(Mesh(), name) for name in ('A', 'B')]
    scene.groups.extend(groups); scene.selection.update(groups)
    history = History(scene)
    vp = SimpleNamespace(scene=scene, history=history, update=lambda: None)
    panel = BimPanel(SimpleNamespace(viewport=vp))
    panel.name_edit.setText('Both'); panel._on_tag()
    assert all(g.ifc['name'] == 'Both' for g in groups)
    ids = [g.ifc['guid'] for g in groups]; assert ids[0] != ids[1]
    history.undo(); assert all(g.ifc is None for g in groups)
    history.redo(); assert [g.ifc['guid'] for g in groups] == ids
    panel._on_untag(); assert all(g.ifc is None for g in groups)
    history.undo(); assert [g.ifc['guid'] for g in groups] == ids
    panel.close()


def test_dialog_surfaces_userdefined():
    from views.object_record import RecordDialog
    app = QApplication.instance() or QApplication([])
    dialog = RecordDialog(None, {'class': 'IfcWall'}, registry())
    dialog.predefined.setCurrentText('USERDEFINED'); dialog.submit()
    assert 'object_type' in dialog.error.text()
    assert dialog.patch is None
    dialog.fields['object_type'].setText('Ride'); dialog.submit()
    assert dialog.patch['object_type'] == 'Ride'


def test_paste_with_layers_preserves_record():
    from tests.test_paste_tags import _source, _clip, _VP
    from tools.paste import PasteTool
    clip = _clip(_source()); original = clip['groups'][0]
    original.ifc = full_record()
    scene = Scene(); vp = _VP(scene, clip)
    assert PasteTool.in_place(vp)
    pasted = scene.groups[-1]
    ensure_guid(pasted.ifc)
    guid = pasted.ifc['guid']
    assert guid != original.ifc['guid']
    assert pasted.ifc['psets'] == original.ifc['psets']
    assert scene.layer('Furniture')
    vp.history.undo(); assert not scene.groups and scene.layer('Furniture') is None
    vp.history.redo(); assert scene.groups[-1].ifc['guid'] == guid
    scene.groups[-1].ifc['psets']['Custom']['text']['value'] = 'copy only'
    assert original.ifc['psets']['Custom']['text']['value'] == 'a'


def test_face_tags_undo_and_geometry():
    from PySide6.QtGui import QVector3D
    scene = Scene()
    f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 0)])
    history = History(scene)
    serial = scene.mesh._mut_serial
    history.execute(SetFaceTagsCommand([f], 'IfcWall', 'Wall'))
    tag = deepcopy(f.attrs['ifc'])
    assert set(tag) == {'id', 'class', 'name', 'guid'}
    history.undo(); assert 'ifc' not in f.attrs
    history.redo(); assert f.attrs['ifc'] == tag
    history.execute(SetFaceTagsCommand([f])); assert 'ifc' not in f.attrs
    history.undo(); assert f.attrs['ifc'] == tag
    assert scene.mesh._mut_serial == serial


def test_legacy_record_round_trip(tmp_path):
    scene = Scene(); group = Group(Mesh(), 'Legacy'); scene.groups.append(group)
    group.ifc = {'class': 'IfcBeam', 'name': 'Legacy'}; ensure_guid(group.ifc)
    path = tmp_path / 'legacy.igz'; igz.save_scene(scene, path)
    loaded = Scene(); igz.load_into(loaded, path)
    assert record.normalize(loaded.groups[0].ifc) == group.ifc
    assert not record.validate(loaded.groups[0].ifc, registry())


def test_dialog_patch_carries_only_what_changed():
    """One dialog over a multi-selection: the first object's name must not
    land on the others, only the edited fields travel."""
    from views.object_record import RecordDialog
    app = QApplication.instance() or QApplication([])
    scene = Scene(); groups = [Group(Mesh(), name) for name in ('Pier 1', 'Pier 2')]
    scene.groups.extend(groups)
    history = History(scene)
    history.execute(TagGroupsCommand(groups, 'IfcColumn', ''))
    history.execute(SetRecordCommand([groups[0]], {'name': 'Pier 1', 'tag': 'P1'}))
    history.execute(SetRecordCommand([groups[1]], {'name': 'Pier 2', 'tag': 'P2'}))
    dialog = RecordDialog(None, groups[0].ifc, registry())
    dialog.predefined.setCurrentText('PILASTER'); dialog.submit()
    assert dialog.patch == {'predefined_type': 'PILASTER'}
    history.execute(SetRecordCommand(groups, dialog.patch))
    assert [g.ifc['name'] for g in groups] == ['Pier 1', 'Pier 2']
    assert [g.ifc['tag'] for g in groups] == ['P1', 'P2']
    assert all(g.ifc['predefined_type'] == 'PILASTER' for g in groups)
    # A fresh record keeps its class even when the default was not touched.
    fresh = RecordDialog(None, None, registry()); fresh.submit()
    assert fresh.patch == {'class': 'IfcWall'}
