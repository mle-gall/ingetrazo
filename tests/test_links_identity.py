"""Link identities belong to source placements, independent of labels and reloads."""
from core import links
from core.group import Group, iter_placements
from core.scene import Scene
from formats import igz
from PySide6.QtGui import QMatrix4x4


def source(tmp_path):
    scene = Scene()
    scene.groups = [Group(name='part ' + str(i)) for i in range(5)]
    path = tmp_path / 'parts.igz'
    igz.save_scene(scene, path)
    return scene, path


def test_stable_hosts_subset_and_rename(tmp_path):
    src, path = source(tmp_path)
    host = Scene()
    selected = [g.uid for g in src.groups[:2]]
    group = links.make_link(host, path, select={'uids': selected})
    host.groups.append(group)
    expected = [c.uid for c in group.children]
    assert expected == [links.stable_uid(group.uid, uid) for uid in selected]
    for name in ('one', 'two'):
        file = tmp_path / (name + '.igz')
        igz.save_scene(host, file)
        for _ in range(2):
            loaded = Scene()
            igz.load_into(loaded, file)
            assert [c.uid for c in loaded.groups[0].children] == expected
    src.groups[0].name = 'renamed'
    igz.save_scene(src, path)
    links.reload(host, path)
    assert [c.uid for c in group.children] == expected
    assert group.children[0].name == 'renamed'
    other = links.make_link(host, path, select={'uids': selected})
    assert set(expected).isdisjoint(c.uid for c in other.children)


def test_filter_and_ancestor_transform(tmp_path):
    src, path = source(tmp_path)
    child = src.groups[0]
    parent = Group(name='parent')
    parent.adopt([child])
    parent.xform.translate(7, 0, 0)
    src.groups = [parent]
    igz.save_scene(src, path)
    host = Scene()
    group = links.make_link(host, path, select={'filter': {'facet': 'name', 'eq': child.name}})
    assert len(group.children) == 1
    assert group.children[0].xform.column(3).x() == 7


def test_ride_read_only():
    import os
    from pathlib import Path
    import pytest
    if not os.environ.get('INGETRAZO_TEST_RIDE'):
        pytest.skip('opt-in real read-only fixture')
    path = Path('/Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz')
    before = path.stat().st_mtime_ns
    rows = []
    for _ in range(2):
        scene = Scene()
        igz.load_into(scene, path)
        assert not scene.link_errors
        rows.append([row['uid'] for row in __import__('core.facets', fromlist=['build']).build(scene).values() if row['linked']])
    assert rows[0] and rows[0] == rows[1]
    assert path.stat().st_mtime_ns == before
