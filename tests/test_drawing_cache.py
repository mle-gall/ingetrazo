"""Disk drawing caches are exact, disposable and never authoritative."""
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtGui import QVector3D
from core.mesh import Mesh, DeferredMesh
from core.scene import Scene
from core.group import Group
from formats import igz
from views import array_bake, drawing_cache
from tests.test_viewport_smooth_shading import _cylinder
from tests.test_array_bake import _compare


@pytest.fixture
def cache(tmp_path, monkeypatch):
    db = drawing_cache.Store(tmp_path / 'drawing.sqlite')
    monkeypatch.setattr(drawing_cache, '_STORE', db)
    yield db
    db.close()


def test_typed_codec_and_corruption():
    value = {('path', 0.5): b'\0abc', 'array': np.arange(15, dtype=np.float32).reshape(5, 3),
             'empty': np.zeros((0, 3)), 'list': [None, True, 'x'], 'repeated': [None] * 1000}
    raw = drawing_cache.pack(value)
    got = drawing_cache.unpack(raw)
    assert got[('path', 0.5)] == value[('path', 0.5)]
    assert np.array_equal(got['array'], value['array'])
    assert got['empty'].shape == (0, 3)
    assert got['list'] == value['list']
    assert got['repeated'] == value['repeated']
    with pytest.raises((ValueError, __import__('zlib').error)):
        drawing_cache.unpack(raw[:20])
    with pytest.raises(ValueError):
        drawing_cache.pack(np.array([object()], dtype=object))


def test_cached_bake_matches_fresh_and_invalidates_inputs(cache, tmp_path, monkeypatch):
    from core import _native
    if _native.available() is None or _native.qt_hypot() is None:
        pytest.skip('native array renderer required')
    monkeypatch.setattr(_native, 'native', _native.available())
    monkeypatch.setattr(_native, 'wanted', lambda: True)
    monkeypatch.setattr(igz, '_LARGE_DOCUMENT', 0)
    monkeypatch.setattr(igz, '_BULK_MIN', 1)
    scene = Scene(); scene.groups.append(Group(_cylinder(Mesh()), 'tube'))
    path = tmp_path / 'tube.igz'; igz.save_scene(scene, path)
    def mesh():
        scene = Scene(); igz.load_into(scene, path)
        return scene.groups[0].mesh
    vp = SimpleNamespace(_LIGHT=QVector3D(1, 2, 3).normalized(),
                         DEFAULT_FACE_COLOR=(0.8, 0.8, 0.8))
    first = mesh()
    a = array_bake.bake(vp, first, None, None, (1, 2), 1)
    cache.pending.join()
    second = mesh()
    assert isinstance(second, DeferredMesh)
    original = array_bake._bake_uncached
    monkeypatch.setattr(array_bake, '_bake_uncached', lambda *a: pytest.fail('cache missed'))
    b = array_bake.bake(vp, second, None, None, (5, 6), 2)
    _compare(a, b)
    assert b['mesh'] is second and b['uid'] == 2 and b['vkey'] == (5, 6)
    assert b['faces'].mesh is second
    assert type(second) is DeferredMesh
    _ = second.faces
    assert '_drawing_staged' not in second.__dict__
    assert '_drawing_source_key' not in second.__dict__
    assert drawing_cache.restore(vp, mesh(), {'color': (1, 0, 0)}) is None
    vp._LIGHT = QVector3D(0, 1, 0)
    assert drawing_cache.restore(vp, mesh(), None) is None
    vp._LIGHT = QVector3D(1, 2, 3).normalized()
    changed = mesh()
    changed.__dict__['_deferred_source']['flags'] = changed.__dict__['_deferred_source']['flags'].copy()
    changed.__dict__['_deferred_source']['flags'][0] ^= 1
    assert drawing_cache.restore(vp, changed, None) is None
    monkeypatch.setattr(array_bake, '_bake_uncached', original)
    key = drawing_cache.key_for(vp, first, None)
    cache.reader.execute('UPDATE entries SET value=? WHERE key=?', (b'broken', key));cache.reader.commit()
    cache._hot.clear(); cache._hot_bytes = 0
    fresh = array_bake.bake(vp, mesh(), None, None, (7, 8), 3)
    _compare(a, fresh)


def test_cache_covers_textures_transparency_hidden_faces_and_back_paint(cache, tmp_path, monkeypatch):
    import random
    from core import _native
    from PySide6.QtGui import QImage
    from tests.test_array_bake import _paint_up
    from tests.test_deferred_mesh import _meshes, _random_scene
    if _native.available() is None or _native.qt_hypot() is None:
        pytest.skip('native array renderer required')
    monkeypatch.setattr(_native, 'native', _native.available())
    monkeypatch.setattr(_native, 'wanted', lambda: True)
    monkeypatch.setattr(igz, '_LARGE_DOCUMENT', 0)
    monkeypatch.setattr(igz, '_BULK_MIN', 1)
    png = tmp_path / 'texture.png'
    image = QImage(4, 4, QImage.Format_RGBA8888); image.fill(0xffaabbcc);image.save(str(png))
    rng = random.Random(24)
    scene = _random_scene(rng); _paint_up(scene, rng, png)
    path = tmp_path / 'painted.igz';igz.save_scene(scene, path)
    a, b = Scene(), Scene();igz.load_into(a, path);igz.load_into(b, path)
    vp = SimpleNamespace(_LIGHT=QVector3D(1, 2, 3).normalized(), DEFAULT_FACE_COLOR=(0.8, 0.8, 0.8))
    for first, second in zip(_meshes(a), _meshes(b)):
        if not array_bake.can_bake(first): continue
        fresh = array_bake.bake(vp, first, None, None, 1, 1)
        cache.pending.join()
        hit = drawing_cache.restored_chunk(vp, second, None, None, 2, 2)
        assert hit is not None
        _compare(fresh, hit)
    # Texture content is an input even when its filename is unchanged.
    m = next(m for m in _meshes(b) if array_bake.can_bake(m))
    paint = {'texture': {'path': str(png), 'sw': 1, 'sh': 1}}
    before = drawing_cache.key_for(vp, m, paint)
    image.fill(0x00aabbcc);image.save(str(png))
    assert drawing_cache.key_for(vp, m, paint) != before


def test_broken_cache_is_a_miss_and_size_is_bounded(cache, monkeypatch):
    monkeypatch.setattr(drawing_cache, '_MAX_BYTES', 250)
    for i in range(20):
        cache.put(str(i), {'data': bytes(range(100))})
        cache.pending.join()
    size = cache.reader.execute('SELECT coalesce(sum(length(value)),0) FROM entries').fetchone()[0]
    assert size <= 250
    cache.reader.execute('INSERT OR REPLACE INTO entries VALUES (?,?)', ('broken', b'bad'))
    cache.reader.commit()
    assert cache.get('broken') is None


def test_unwritable_cache_location_disables_only_the_cache(tmp_path, monkeypatch):
    blocked = tmp_path / 'file';blocked.write_text('not a directory')
    monkeypatch.setenv('INGETRAZO_DRAWING_CACHE_DIR', str(blocked / 'cache'))
    monkeypatch.setattr(drawing_cache, '_STORE', None)
    assert drawing_cache.store() is False


def test_cached_read_keeps_progress_pumping(monkeypatch):
    import itertools
    import time
    events = []
    with monkeypatch.context() as patch:
        ticks = itertools.count(0, 0.3)
        patch.setattr(time, 'monotonic', lambda: next(ticks))
        patch.setattr(array_bake, 'can_bake', lambda m: True)
        patch.setattr(drawing_cache, 'restore', lambda *args: None)
        array_bake.restore_cached(None, [(object(), None) for _ in range(3)],
                                  progress=lambda *args: events.append(args))
    assert len(events) == 3
