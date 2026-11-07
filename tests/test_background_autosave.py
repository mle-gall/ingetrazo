import threading
import time
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D as V
from core import autosave
from core.scene import Scene
from formats import igz
from formats.igz_snapshot import snapshot_steps
from tests.test_project_tabs import win, _edit, _settle


def drain(steps):
    while True:
        try: next(steps)
        except StopIteration as done: return done.value


def until(predicate, timeout=10):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:
        _settle(10)
    assert predicate()


@pytest.fixture(autouse=True)
def slots(tmp_path, monkeypatch):
    d=tmp_path/'autosaves';d.mkdir()
    monkeypatch.setattr(autosave,'autosave_dir',lambda:d)


def test_snapshot_roundtrip_and_detachment(tmp_path):
    from tests.test_igz_format3 import _scene
    scene=_scene(tmp_path)
    snapshot=drain(snapshot_steps(scene))
    # Mutating metadata and geometry after capture cannot change the worker input.
    scene.mesh.vertices[0].position=V(999,999,999)
    scene.groups[0].name='changed after snapshot'
    path=tmp_path/'snapshot.igz'
    igz.write_prepared(snapshot,path,background=True)
    loaded=Scene();igz.load_into(loaded,path)
    assert loaded.groups[0].name=='Silla 0'
    assert max(v.position.x() for v in loaded.mesh.vertices)<100
    assert loaded.groups[0].mesh is loaded.groups[1].mesh
    assert any(e.soft for e in loaded.mesh.edges)
    assert any(e.hidden for e in loaded.mesh.edges)
    assert any(f.attrs.get('texture') for f in loaded.mesh.faces)


def test_worker_does_not_block_ui_or_publish_after_clear(win, monkeypatch):
    _edit(win)
    release=threading.Event();started=threading.Event()
    original=igz.write_prepared
    ui=threading.get_ident();worker=[]
    def slow(*args,**kwargs):
        worker.append(threading.get_ident());started.set()
        assert release.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(igz,'write_prepared',slow)
    ticks=[];heartbeat=QTimer();heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda:ticks.append(1));heartbeat.start()
    try:
        win._on_autosave_tick()
        manager=win._background_autosave
        until(started.is_set)
        _settle(60)
        assert len(ticks)>1 and worker==[worker[0]] and worker[0]!=ui
        doc=win.active_document()
        autosave.clear(doc.path,untitled=doc.untitled_no)
        release.set()
        until(lambda:not manager.busy)
        assert autosave.pending(doc.path,untitled=doc.untitled_no) is None
        assert doc.autosaved_version is None
    finally:
        release.set();heartbeat.stop()


def test_edit_during_capture_restarts_and_saves_latest(win):
    _edit(win,z=1)
    win._on_autosave_tick();manager=win._background_autosave
    manager.timer.stop()
    manager.SLICE_SECONDS=0  # leave capture pending, then edit the live model
    manager.advance()
    old=manager.job['version']
    _edit(win,z=3)
    manager.advance()
    assert manager.job is None
    manager.SLICE_SECONDS=.006;manager.timer.start()
    until(lambda:not manager.busy)
    doc=win.active_document()
    assert doc.autosaved_version>old
    loaded=Scene();igz.load_into(loaded,autosave.pending(doc.path,doc.untitled_no))
    assert any(e.a.z()==3 for e in loaded.mesh.edges)


def test_edit_during_write_stays_dirty_for_next_autosave(win, monkeypatch):
    _edit(win,z=1)
    release=threading.Event();started=threading.Event()
    original=igz.write_prepared
    def slow(*args,**kwargs):
        started.set();assert release.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(igz,'write_prepared',slow)
    try:
        win._on_autosave_tick();manager=win._background_autosave
        until(started.is_set)
        _edit(win,z=4);release.set()
        until(lambda:not manager.busy)
        doc=win.active_document()
        assert doc.autosaved_version<doc.viewport.scene.content_version
        win._on_autosave_tick()
        until(lambda:not manager.busy)
        assert doc.autosaved_version==doc.viewport.scene.content_version
    finally:
        release.set()


def test_failed_write_keeps_previous_recovery(win, monkeypatch):
    _edit(win,z=1)
    win._on_autosave_tick();manager=win._background_autosave
    until(lambda:not manager.busy)
    doc=win.active_document();slot=autosave.pending(doc.path,doc.untitled_no)
    old=slot.read_bytes();version=doc.autosaved_version
    _edit(win,z=7)
    def fail(*args,**kwargs): raise OSError('disk full')
    monkeypatch.setattr(igz,'write_prepared',fail)
    win._on_autosave_tick()
    until(lambda:not manager.busy)
    assert slot.read_bytes()==old
    assert doc.autosaved_version==version
    assert manager.last_error=='disk full'


def test_deferred_mesh_snapshot_does_not_materialize_source(tmp_path, monkeypatch):
    from tests.test_igz_format3 import _scene
    from core.mesh import DeferredMesh
    monkeypatch.setattr(igz,'_LARGE_DOCUMENT',0)
    monkeypatch.setattr(igz,'_BULK_MIN',1)
    scene=_scene(tmp_path)
    path=tmp_path/'source.igz';igz.save_scene(scene,path)
    loaded=Scene();igz.load_into(loaded,path)
    # Depending on the configured engine, load may already materialize it;
    # both forms must round-trip, and deferred sources must stay deferred.
    kind=type(loaded.groups[0].mesh)
    snap=drain(snapshot_steps(loaded))
    assert type(loaded.groups[0].mesh) is kind
    out=tmp_path/'copy.igz';igz.write_prepared(snap,out,background=True)
    copy=Scene();igz.load_into(copy,out)
    assert len(copy.groups)==len(loaded.groups)
    assert len(copy.groups[0].mesh.faces)==len(loaded.groups[0].mesh.faces)


def test_snapshot_while_editing_preserves_root_and_group(tmp_path):
    from core.group import Group
    from core.mesh import Mesh
    scene=Scene()
    scene.mesh.add_edge(V(0,0,9),V(1,0,9))
    g=Group(Mesh(),'edited')
    g.mesh.add_edge(V(0,0,2),V(1,0,2))
    scene.groups.append(g)
    scene.begin_group_edit(g)
    snap=drain(snapshot_steps(scene))
    path=tmp_path/'editing.igz';igz.write_prepared(snap,path,background=True)
    recovered=Scene();igz.load_into(recovered,path)
    assert len(recovered.mesh.edges)==1
    assert recovered.mesh.edges[0].a.z()==9
    assert recovered.groups[0].mesh.edges[0].a.z()==2
    assert scene.edit_group is g  # saving never closes the user's group


def test_survey_arrays_and_images_are_detached(tmp_path):
    from tests.test_photomesh import _write_odm_tree, _datum_at_anchor
    from georef.photomesh import load_odm_obj
    from PySide6.QtGui import QImage
    import numpy as np
    scene=Scene()
    scene.photo_mesh=load_odm_obj(_write_odm_tree(tmp_path),_datum_at_anchor())
    image=QImage(8,8,QImage.Format_RGB32);image.fill(0xff3366aa)
    scene.photo_mesh.images={0:image}
    expected=scene.photo_mesh.vertices.copy()
    snap=drain(snapshot_steps(scene))
    scene.photo_mesh.vertices[:]=999
    scene.photo_mesh.images[0].fill(0xffff0000)
    path=tmp_path/'survey-snapshot.igz'
    igz.write_prepared(snap,path,background=True)
    recovered=Scene();igz.load_into(recovered,path)
    np.testing.assert_array_equal(recovered.photo_mesh.vertices,expected)
    assert recovered.photo_mesh.images[0].pixelColor(0,0).blue()>100


def test_trackpad_camera_motion_defers_snapshot_slices(win):
    _edit(win)
    win._on_autosave_tick();manager=win._background_autosave
    manager.timer.stop();manager.SLICE_SECONDS=0
    manager.advance()
    win.viewport.camera.distance *= .9
    manager.advance()
    assert manager.job['navigation_until']>time.monotonic()
    assert not manager.writing
    manager.cancel()
    assert not manager.busy
