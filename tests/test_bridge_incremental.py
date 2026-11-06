"""Bridge inspection stays read-only; local edits retain unrelated bakes."""
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from plugins.ai_bridge import _Bridge
from tests.test_chunk_stale_materials import _stub


def _group(name):
    mesh = Mesh()
    mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])
    return Group(mesh, name=name)


def test_refresh_retains_untouched_chunk_and_rebuilds_replaced_mesh():
    scene = Scene()
    changed, untouched = _group('changed'), _group('untouched')
    scene.groups.extend([changed, untouched])
    vp = _stub(scene)
    signals = []
    vp.sceneVersionChanged = SimpleNamespace(emit=signals.append)
    updates = []
    vp.update = lambda: updates.append(True)
    old = vp._group_chunk(changed)
    kept = vp._group_chunk(untouched)
    original = changed.mesh
    replacement = _group('replacement').mesh
    replacement.add_face([V(0, 0, 1), V(1, 0, 1), V(0, 1, 1)])
    changed.mesh = replacement
    scene.version += 1
    content_version = scene.content_version
    vp.refresh_after_edit()
    assert scene.content_version == content_version
    assert vp._group_chunk(untouched) is kept
    assert vp._group_chunk(changed)['nf'] == 2
    assert vp._group_chunk(changed) is not old
    assert len(updates) == len(signals) == 1
    # An undo restoring the old mesh must invalidate the changed bake again.
    changed.mesh = original
    scene.version += 1
    vp.refresh_after_edit()
    assert vp._group_chunk(changed)['nf'] == 1
    assert vp._group_chunk(untouched) is kept


def test_queries_do_not_snapshot_redraw_or_compute_bounds(monkeypatch):
    scene = Scene()
    parent, child = _group('Support'), _group('support child')
    parent.children = [child]
    scene.groups = [parent]
    def forbidden(*args, **kwargs):
        pytest.fail('read-only query entered an expensive/mutating path')
    monkeypatch.setattr(scene.mesh, 'capture_state', forbidden)
    monkeypatch.setattr(scene, 'bounds', forbidden)
    vp = SimpleNamespace(scene=scene, history=SimpleNamespace(execute=forbidden),
                         update=forbidden, notify_scene_changed=forbidden)
    bridge = SimpleNamespace(_viewport=vp, _scope={'job_status': {'done': True}})
    version = scene.version
    result = _Bridge._tool_query_model(bridge, include_bounds=False)
    assert result['bounds'] is None
    page = _Bridge._tool_query_groups(bridge, name='SUPPORT', limit=1)
    assert page['groups'][0]['uid'] == parent.uid
    page2 = _Bridge._tool_query_groups(bridge, offset=page['next_offset'], limit=1)
    assert page2['groups'][0]['path'] == [parent.uid, child.uid]
    assert page2['next_offset'] is None
    status = _Bridge._tool_query_status(bridge, 'job_status')
    status['value']['done'] = False
    assert bridge._scope['job_status']['done'] is True
    assert _Bridge._tool_query_status(bridge, 'missing')['found'] is False
    bridge._scope['unsafe'] = scene
    with pytest.raises(ValueError):
        _Bridge._tool_query_status(bridge, 'unsafe')
    assert scene.version == version


@pytest.mark.parametrize('args', [{'limit': 0}, {'limit': 1001}, {'offset': -1},
                                  {'offset': True}, {'name': 42}])
def test_query_groups_rejects_invalid_pagination(args):
    with pytest.raises(ValueError):
        _Bridge._tool_query_groups(SimpleNamespace(), **args)
