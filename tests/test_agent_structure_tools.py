"""Exercise the registered callables with the same JSON boundary as the bridge."""
from types import SimpleNamespace
import pytest

from core.agent_structure import StructureTools
from core.agent_tools import BUILTIN_TOOLS, json_value, register
from core.group import Group
from core.history import History
from core.scene import Scene


def test_catalog_round_trip():
    scene = Scene()
    g, ref = Group(name='Beam'), Group(name='Survey point')
    scene.groups = [g, ref]
    agent = StructureTools()
    history = History(scene)
    agent._viewport = SimpleNamespace(scene=scene, history=history)
    catalog = {}
    for spec in BUILTIN_TOOLS:
        fn = getattr(agent, '_tool_' + spec['name'], None)
        if fn:
            register(catalog, spec['name'], fn, description=spec['description'],
                     input_schema=spec['inputSchema'], mutates=spec['mutates'])
    assert set(catalog) == {'query_structure', 'set_structure', 'file', 'query_unsorted', 'bootstrap_structure'}
    assert {k for k, v in catalog.items() if v['mutates']} == {'set_structure', 'file', 'bootstrap_structure'}

    def call(name, **args):
        spec = catalog[name]
        assert set(spec['input_schema']['required']) <= args.keys() <= spec['input_schema']['properties'].keys()
        return json_value(spec['fn'](**json_value(args)))

    assert call('query_unsorted', limit=1)['next_offset'] == 1
    with pytest.raises(ValueError):
        agent._tool_query_unsorted(limit=0)
    value = dict(nodes={'b': dict(name='Beams', parent=None, order=1, recipe={'class': 'IfcBeam'})}, active='b')
    assert call('set_structure', value=value)['applied']
    call('file', uids=[g.uid], node='b')
    assert len(history.undo_stack) == 2
    q = call('query_structure')
    assert q['active'] == 'b' and q['roots'] == ['b'] and q['nodes']['b']['members'] == 1
    assert call('query_unsorted')['rows'][0]['uid'] == ref.uid
    call('set_structure', patch={'b': {'name': 'Framing'}})
    assert g.layer == 'Framing'
    history.undo()
    assert g.layer == 'Beams'
    with pytest.raises(ValueError):
        call('set_structure', patch={'b': dict(recipe={'class': 'Typo'})})
    with pytest.raises(ValueError, match='occupied'):
        call('set_structure', value={})
    assert call('set_structure', value={}, force=True)['unfiled'] == [g.uid]
    history.undo()
    ref.ext = {'link': {'path': 'source.igz'}}
    with pytest.raises(ValueError, match='Linked'):
        call('file', node='b', uids=[ref.uid])
    depth = len(history.undo_stack)
    preview = call('bootstrap_structure')
    assert not preview['applied'] and len(history.undo_stack) == depth
    result = call('bootstrap_structure', apply=True)
    assert result['structure'] == preview['structure'] and len(history.undo_stack) == depth + 1
    history.undo()
    assert call('query_structure') == q


def test_bridge_and_mcp_share_catalog(monkeypatch):
    from tests.test_agent_tools import call
    from tests.test_mcp_client_host import _client
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        bridge = _Bridge(win.viewport)
        client = _client(monkeypatch)
        monkeypatch.setattr(client, '_bridge', lambda tool, args: dict(ok=True, result=call(bridge, tool, **args)))
        tools = client.handle(dict(id=1, method='tools/list'))['result']['tools']
        specs = {s['name']: s for s in tools}
        assert specs['query_structure']['annotations']['readOnlyHint']
        assert not specs['bootstrap_structure']['annotations']['readOnlyHint']
        g = Group(name='Sample')
        win.viewport.scene.groups = [g]
        call(bridge, 'set_structure', value={'nodes': {'sample': dict(name='Sample', parent=None, order=0)}})
        assert call(bridge, 'file', uids=[g.uid], node='sample')['applied']
        assert call(bridge, 'query_structure')['nodes']['sample']['members'] == 1
        assert call(bridge, 'undo')['ok']
        assert call(bridge, 'query_unsorted')['rows'][0]['uid'] == g.uid
        win.viewport.scene.worksession_read_only = True
        assert not call(bridge, 'bootstrap_structure')['applied']
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
