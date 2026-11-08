"""Navigator expressions, atomic rules and display-only visibility."""
import pytest
from core.scene import Scene
from core.group import Group
from core import facets, bim_registry
from core.history import History


def model():
    scene = Scene()
    parent = Group(name='Launch')
    child = Group(name='Pier 1')
    child.ifc = {'class': 'IfcColumn', 'classifications': [dict(system='discipline', code='S', name='Structural')], 'systems': ['launch', 'launch']}
    parent.children = [child]
    other = Group(name='Track')
    scene.groups = [parent, other]
    return scene, parent, child, other


def test_filters_and_counts():
    scene, parent, child, other = model()
    index = facets.build(scene)
    assert facets.build(scene) is index
    assert facets.evaluate(index, {'all': [{'text': 'pier*'}, {'facet': 'depth', 'gt': 0}]}) == [child.uid]
    assert facets.evaluate(index, {'any': [{'facet': 'class', 'eq': 'IfcColumn'}, {'facet': 'name', 'glob': 'TR*'}]}) == [child.uid, other.uid]
    assert facets.evaluate(index, {'not': {'facet': 'class', 'exists': True}}) == [parent.uid, other.uid]
    assert facets.values(index, 'system') == {'launch': 1}
    assert index[child.uid]['path_uids'] == [parent.uid]
    scene.version += 1
    assert facets.build(scene) is not index


@pytest.mark.parametrize('expr', [{'bad': 1}, {'facet': 'name', 'glob': 2}, {'all': {}}, {'facet': 'depth', 'gt': True}])
def test_invalid_filters(expr):
    with pytest.raises(ValueError):
        facets.validate_filter(expr)


def test_rule_one_undo_and_link_guard():
    scene, parent, child, other = model()
    history = History(scene)
    registry = bim_registry.seed_defaults()
    registry['systems']['launch'] = dict(name='Launch', ifc_class='IfcSystem')
    registry['rules']['structure'] = dict(name='Structure', filter={'facet': 'class', 'eq': 'IfcColumn'}, apply={'patch': {'description': 'Reviewed'}, 'classifications': [dict(system='discipline', code='A', name='Architecture')]})
    assert facets.apply_rule(scene, history, registry, 'structure') == [child.uid]
    assert len(child.ifc['classifications']) == 2
    history.undo()
    assert 'description' not in child.ifc
    parent.ext = {'link': {'path': '/reference.igz'}}
    scene.version += 1
    with pytest.raises(ValueError, match='Linked'):
        facets.apply_rule(scene, history, registry, 'structure')
    assert 'description' not in child.ifc


def test_display_parent_child_and_previous():
    from core.agent_facets import set_display, previous_display
    from types import SimpleNamespace
    scene, parent, child, other = model()
    vp = SimpleNamespace(scene=scene, update=lambda: None)
    set_display(vp, {'facet': 'name', 'eq': 'Launch'}, 'kind:discipline')
    assert scene.entity_visible(child)
    assert not scene.entity_selectable(other)
    set_display(vp, {'facet': 'name', 'eq': 'Pier 1'})
    assert scene.entity_visible(child)
    assert not scene.entity_visible(parent)
    previous_display(vp)
    assert scene.entity_visible(parent)
    set_display(vp)
    assert scene.entity_visible(other)


def test_registry_validation():
    reg = bim_registry.seed_defaults()
    reg['views']['bad'] = dict(name='bad', filter={'facet': 'name', 'in': 5}, isolate='yes')
    assert len(bim_registry.validate(reg)) == 2


def test_tint_overrides_face_material_and_nested_proxy():
    from types import SimpleNamespace
    from core.agent_facets import set_display
    from core.materials import effective_attrs
    from views.viewport import Viewport, _paint_of
    scene, parent, child, other = model()
    vp = SimpleNamespace(scene=scene, update=lambda: None)
    set_display(vp, {'facet': 'name', 'eq': 'Pier 1'}, 'kind:discipline')
    proxies = Viewport._expand_placements(vp, parent)
    assert proxies[1].uid == child.uid
    assert scene.entity_selectable(proxies[1])
    paint = _paint_of(vp, proxies[1])
    attrs = effective_attrs({'mat': 'Red', 'color': (1, 0, 0)}, paint)
    assert attrs['color'] == facets.palette(['S'])
    assert 'mat' not in attrs


def test_saved_scene_keeps_view_key():
    from core.saved_views import SavedView
    view = SavedView('Launch', navigator_view='launch')
    assert SavedView.from_dict(view.to_dict()).navigator_view == 'launch'


def test_hide_exact_complement_survives_previous():
    from core.agent_facets import set_display, previous_display
    from types import SimpleNamespace
    scene, parent, child, other = model()
    vp = SimpleNamespace(scene=scene, update=lambda: None)
    set_display(vp, {'not': {'facet': 'name', 'eq': 'Pier 1'}}, exact=True)
    assert not scene.entity_visible(child)
    set_display(vp)
    previous_display(vp)
    assert not scene.entity_selectable(child)


def test_bridge_saved_views_and_paging():
    from core.agent_facets import FacetTools
    from types import SimpleNamespace
    scene, parent, child, other = model()
    agent = FacetTools()
    agent._viewport = SimpleNamespace(scene=scene, history=History(scene), update=lambda: None)
    assert agent._tool_query_facets(facets=['system']) == {'system': {'launch': 1}}
    page = agent._tool_query_view(limit=1)
    assert page['total'] == 3 and page['next_offset'] == 1
    agent._tool_save_view('columns', 'Columns', {'facet': 'class', 'eq': 'IfcColumn'}, isolate=True)
    assert agent._tool_apply_view('columns')['uids'] == [child.uid]
    assert not scene.entity_selectable(other)
    agent._tool_set_view_filter()
    assert scene.entity_selectable(other)


def test_dock_missing_values_and_or_choices():
    from types import SimpleNamespace
    from PySide6.QtWidgets import QMainWindow
    from views.navigator import NavigatorDock
    scene, parent, child, other = model()
    window = QMainWindow()
    window.viewport = SimpleNamespace(scene=scene, history=History(scene), update=lambda: None)
    dock = NavigatorDock(window)
    dock.index = facets.build(scene)
    dock.checked = {'class': {None}}
    dock.refilter()
    assert dock.result_uids == [parent.uid, other.uid]
    dock.checked = {'name': {'Launch', 'Pier 1'}}
    dock.refilter()
    assert dock.result_uids == [parent.uid, child.uid]
    dock.close()
    window.close()


def test_filtered_ifc_profile_exports_only_matching_group(tmp_path):
    from PySide6.QtGui import QVector3D
    from formats.ifc import save_ifc
    scene = Scene()
    for name in ('Keep', 'Omit'):
        group = Group(name=name)
        group.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0)])
        group.ifc = {'class': 'IfcSlab', 'name': name}
        scene.groups.append(group)
    registry = bim_registry.seed_defaults()
    registry['export_profiles']['one'] = dict(schema='IFC4', filter={'facet': 'name', 'eq': 'Keep'})
    scene.plugin_data['bim_registry'] = registry
    path = tmp_path / 'one.ifc'
    save_ifc(scene, path, profile='one')
    text = path.read_text()
    assert text.count('IFCSLAB(') == 1
    assert "'Keep'" in text and "'Omit'" not in text


def test_result_selection_opens_the_placement_context(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMainWindow
    from views.navigator import NavigatorDock
    scene, parent, child, other = model()
    window = QMainWindow()
    window.viewport = SimpleNamespace(scene=scene, update=lambda: None)
    dock = NavigatorDock(window)
    dock.index = facets.build(scene)
    dock.checked = {'class': {'IfcColumn'}}
    dock.refilter()
    paths = []
    monkeypatch.setattr('views.outliner.open_to', lambda vp, path: paths.append(path) or True)
    item = dock.results.topLevelItem(0)
    item.setSelected(True)
    assert paths[-1] == [parent]
    assert scene.selection == {child}
    dock.close()
    window.close()
