"""Projects share registry and IFC identity across independently loaded hosts."""
import pytest
from core import project, bim_registry
from core.scene import Scene
from core.history import SetRegistryCommand
from formats import project as storage, igz


def test_project_roundtrip_sharing_and_undo(tmp_path):
    a, b = Scene(), Scene()
    path = tmp_path / 'project.igzproj'
    project.create(a, path, tmp_path / 'a.igz')
    project.attach(b, path, tmp_path / 'b.igz')
    value = bim_registry.get(a)
    value['project']['name'] = 'Shared'
    command = SetRegistryCommand(value)
    command.do(a)
    assert bim_registry.get(b)['project']['name'] == 'Shared'
    command.undo(a)
    assert 'name' not in bim_registry.get(b)['project']
    command.do(a)
    igz.save_scene(a, tmp_path / 'a.igz')
    restored = Scene()
    igz.load_into(restored, tmp_path / 'a.igz')
    assert bim_registry.get(restored)['project']['name'] == 'Shared'
    assert restored.plugin_data['ifc_identity'] == b.plugin_data['ifc_identity']
    assert storage.load(path)['files'][0]['path'] == 'a.igz'


def test_conflict_warns_and_last_writer_wins(tmp_path):
    a, b = Scene(), Scene()
    path = tmp_path / 'project.igzproj'
    project.create(a, path)
    project.attach(b, path)
    value = bim_registry.get(a)
    project.write_registry(a, value)
    value['project']['name'] = 'B'
    with pytest.warns(RuntimeWarning, match='last writer wins'):
        project.write_registry(b, value)
    assert bim_registry.get(a)['project']['name'] == 'B'


def test_export_project_guid(tmp_path):
    from core.group import Group
    from PySide6.QtGui import QVector3D
    from formats.ifc import save_ifc
    a, b = Scene(), Scene()
    path = tmp_path / 'shared.igzproj'
    project.create(a, path)
    project.attach(b, path)
    guid = storage.load(path)['ifc_identity']['project']
    for index, scene in enumerate((a, b)):
        group = Group(name='Wall')
        group.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 0, 1)])
        group.ifc = {'class': 'IfcWall'}
        scene.groups.append(group)
        output = tmp_path / f'{index}.ifc'
        save_ifc(scene, output)
        assert "IFCPROJECT('" + guid + "'" in output.read_text()


def test_agent_links_and_project(tmp_path):
    from types import SimpleNamespace
    from core.agent_links import LinkTools
    from core.group import Group
    scene = Scene()
    src = Scene()
    src.groups = [Group(name='part')]
    source = tmp_path / 'source.igz'
    igz.save_scene(src, source)
    from core import links
    def place(path, at, select):
        group = links.make_link(scene, path, select=select)
        scene.groups.append(group)
        return group
    window = SimpleNamespace(link_igz_path=place, _current_path=None, _relink_done=lambda text: None)
    agent = LinkTools()
    agent._viewport = SimpleNamespace(scene=scene, window=lambda: window)
    uid = agent._tool_link_document(str(source), {'uids': [src.groups[0].uid]})['uid']
    assert agent._tool_query_links()[0]['uid'] == uid
    assert agent._tool_reload_link(str(source))[0]['stable_uid_count'] == 1
    path = tmp_path / 'shared.igzproj'
    project.create(Scene(), path)
    agent._tool_set_project(str(path))
    assert agent._tool_query_project()['version'] == 1
