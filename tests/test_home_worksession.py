"""Home and project sessions exercise real tabs with isolated test settings."""
from pathlib import Path
import threading
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QVector3D
from core import project, recent
from core.scene import Scene
from core.history import AddEdgeCommand
from formats import igz
from formats import project as storage


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow(defer_extensions=True)
    yield w
    for d in w.documents():
        d.saved_content = d.viewport.scene.content_version
    w.close()


def make_project(tmp_path):
    path = tmp_path / 'job.igzproj'
    project.create(Scene(), path)
    value = storage.load(path)
    for name, role in [('a', 'host'), ('b', 'host'), ('source', 'linked')]:
        igz.save_scene(Scene(), tmp_path / (name + '.igz'))
        value['files'].append(dict(path=name + '.igz', role=role))
    storage.save(path, value)
    return path


def test_portable_roundtrip(tmp_path):
    path = make_project(tmp_path)
    a, b = tmp_path / 'a.igz', tmp_path / 'b.igz'
    project.save_worksession(path, [dict(path=b, camera={'distance': 7}), dict(path=a)], a)
    state = project.worksession(path)
    assert [r['path'] for r in state['files']] == [str(b), str(a)]
    assert state['files'][0]['camera'] == {'distance': 7}
    assert state['active_file'] == str(a)
    assert storage.load(path)['worksession']['active_file'] == 'a.igz'


def test_recent_bounded_pin_and_relocation(tmp_path):
    st = QSettings(str(tmp_path / 'recent.ini'), QSettings.IniFormat)
    first = tmp_path / 'first.igz'
    recent.remember(first, pinned=True, settings=st)
    for n in range(30):
        recent.remember(tmp_path / f'{n}.igz', settings=st)
    assert len(recent.entries(settings=st)) == recent.LIMIT
    assert recent.entries(settings=st)[0]['path'] == str(first)
    moved = tmp_path / 'moved.igz'
    recent.remember(moved, replace=str(first), settings=st)
    assert recent.entries(settings=st)[0] == dict(path=str(moved), pinned=True)


def test_home_lists_opens_and_locates(win, tmp_path, monkeypatch):
    from views.home import Home
    from views.filedialogs import file_dialogs
    a = tmp_path / 'moved.igz'
    igz.save_scene(Scene(), a)
    old = tmp_path / 'old.igz'
    recent.remember(old)
    recent.remember(make_project(tmp_path))
    home = Home(win)
    assert home.lists['files'].count()
    assert home.lists['projects'].count()
    monkeypatch.setattr(file_dialogs, 'getOpenFileName', lambda *a: (str(tmp_path / 'moved.igz'), ''))
    assert home.open_recent(old)
    assert win._doc.path == a
    assert str(old) not in [r['path'] for r in recent.entries()]


def test_active_file_tabs_and_reopen(win, tmp_path):
    path = make_project(tmp_path)
    assert win.open_project(path)
    assert len(win.documents()) == 2
    a, b = win.documents()
    assert not a.read_only and b.read_only
    win.activate_document(b)
    before = b.viewport.scene.content_version
    b.viewport.history.execute(AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0)))
    assert b.viewport.scene.content_version == before
    win.set_active_file(tmp_path / 'source.igz')
    assert all(d.read_only for d in (a, b))
    source = win._doc
    source.viewport.history.execute(AddEdgeCommand(QVector3D(), QVector3D(1, 0, 0)))
    assert source.viewport.history.undo_stack
    win._do_save(source.path)
    assert next(e for e in storage.load(path)['files'] if e['path'] == 'source.igz')['role'] == 'linked'
    win._project_tabs.tabs.moveTab(win._project_tabs.index_of(source), 0)
    win.persist_worksession()
    assert storage.load(path)['worksession']['files'][0]['path'] == 'source.igz'
    win.open_project(path)
    assert win.documents()[0] is source
    assert win._active_file == str(source.path)


def test_agent_tools_and_read_only_rejection(win, tmp_path):
    from plugins.ai_bridge import _Bridge
    bridge = _Bridge(win.viewport)
    def call(tool, **args):
        job = {'req': {'tool': tool, 'args': args}, 'done': threading.Event()}
        bridge._run_on_main(job)
        return job['reply']
    path = make_project(tmp_path)
    assert call('open_project', path=str(path))['ok']
    assert call('query_worksession')['result']['active_file'].endswith('a.igz')
    win.activate_document(win.documents()[1])
    assert not call('run_python', code='scene.clear()')['ok']
    assert call('set_active_file', path=str(tmp_path / 'b.igz'))['ok']
    assert call('query_recent')['result']['projects']


def test_thumbnail_is_additive_and_survives_resave(tmp_path):
    import zipfile
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QImage
    image = QImage(32, 20, QImage.Format_RGB32)
    image.fill(Qt.white)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    scene = Scene()
    scene._home_thumbnail_png = bytes(data)
    path = tmp_path / 'preview.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    igz.save_scene(loaded, path)
    with zipfile.ZipFile(path) as archive:
        assert archive.read('thumbnail.png') == bytes(data)


def test_missing_project_member_keeps_current_session(win, tmp_path):
    path = make_project(tmp_path)
    (tmp_path / 'a.igz').unlink()
    with pytest.raises(FileNotFoundError):
        win.open_project(path)
    assert win._session_path is None


def test_new_document_can_be_saved_into_session(win, tmp_path):
    path = make_project(tmp_path)
    win.open_project(path)
    win._on_new()
    assert not win._doc.read_only
    assert all(d.read_only for d in win.documents() if d is not win._doc)
    new_path = tmp_path / 'new.igz'
    win._do_save(new_path)
    assert win._active_file == str(new_path)
    assert new_path.is_file()
    assert storage.load(path)['worksession']['active_file'] == 'new.igz'
