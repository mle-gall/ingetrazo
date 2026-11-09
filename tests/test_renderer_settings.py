# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Renderer selection persists while crash recovery covers presentation only."""
import pytest
from PySide6.QtCore import QSettings
from core import general_settings as gs, renderer_settings as rs


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv('INGETRAZO_WGPU', raising=False)
    monkeypatch.setattr(rs, '_checked', False)
    monkeypatch.setattr(rs, 'capability', lambda: rs.Capability(True))
    return QSettings(str(tmp_path/'renderer.ini'), QSettings.IniFormat)


def test_round_trip(settings):
    assert not rs.wanted(settings)
    gs.set_value(rs.SETTING, 'wgpu', settings)
    settings.sync()
    assert rs.wanted(QSettings(settings.fileName(), QSettings.IniFormat))
    gs.set_value(rs.SETTING, 'opengl', settings)
    assert not rs.wanted(settings)


@pytest.mark.parametrize('saved,override,expected', [
    ('wgpu', '0', False), ('opengl', '1', True)])
def test_environment_wins(settings, monkeypatch, saved, override, expected):
    gs.set_value(rs.SETTING, saved, settings)
    monkeypatch.setenv('INGETRAZO_WGPU', override)
    assert rs.wanted(settings) is expected
    rs.arm(settings)
    assert gs.value(rs.STARTING, '0', settings) == '0'


def test_guard_phase_sequence(settings, monkeypatch):
    clock = [0]
    monkeypatch.setattr('time.monotonic', lambda: clock[0])
    gs.set_value(rs.SETTING, 'wgpu', settings)
    assert not rs.start_guard(settings)
    clock[0] += 600  # a very long load is not an attempted renderer start
    assert gs.value(rs.STARTING, '0', settings) == '0'
    rs.arm(settings)
    assert gs.value(rs.STARTING, '0', settings) == '1'
    clock[0] += 600  # a slow frame has no timeout either
    rs.first_frame(settings)
    assert gs.value(rs.STARTING, '1', settings) == '0'
    rs.arm(settings)
    monkeypatch.setattr(rs, '_checked', False)  # next process after crash
    assert rs.start_guard(settings)
    assert not rs.wanted(settings)
    assert not rs.start_guard(settings)

@pytest.mark.parametrize('default', ['opengl', 'wgpu'])
@pytest.mark.parametrize('saved', [None, 'opengl', 'wgpu'])
@pytest.mark.parametrize('override', [None, '0', '1'])
@pytest.mark.parametrize('available', [False, True])
def test_selection_chain(settings, monkeypatch, default, saved, override, available):
    monkeypatch.setattr(rs, 'DEFAULT_RENDERER', default)
    monkeypatch.setattr(rs, 'capability', lambda: rs.Capability(available, 'no adapter'))
    if saved is not None:
        gs.set_value(rs.SETTING, saved, settings)
    if override is not None:
        monkeypatch.setenv('INGETRAZO_WGPU', override)
    requested = (override == '1' if override is not None
                 else (saved or default) == 'wgpu')
    assert rs.wanted(settings) == (requested and available)
    assert gs.value(rs.SETTING, None, settings) == saved


@pytest.mark.parametrize('default', ['opengl', 'wgpu'])
def test_recovery_is_always_opengl(settings, monkeypatch, default):
    monkeypatch.setattr(rs, 'DEFAULT_RENDERER', default)
    gs.set_value(rs.SETTING, 'wgpu', settings)
    gs.set_value(rs.STARTING, '1', settings)
    assert rs.start_guard(settings)
    assert not rs.wanted(settings)
    assert gs.value(rs.SETTING, None, settings) == 'opengl'


def test_status(settings, monkeypatch):
    assert rs.status_text(True, settings) == 'Metal (wgpu)'
    assert rs.status_text(False, settings) == 'OpenGL'
    monkeypatch.setattr(rs, 'capability', lambda: rs.Capability(False, 'no adapter'))
    assert rs.status_text(False, settings) == 'OpenGL — Metal unavailable: no adapter'


def test_missing_crate(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'ingetrazo_render', None)
    cap = rs._probe_local()
    assert not cap.available
    assert 'render crate unavailable' in cap.reason


@pytest.mark.parametrize('fails', [False, True])
def test_adapter_probe(monkeypatch, fails):
    import sys
    from types import SimpleNamespace
    def renderer(*args):
        if fails:
            raise ValueError('no Metal adapter')
        return object()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'ingetrazo_render', SimpleNamespace(Renderer=renderer))
    cap = rs._probe_local()
    assert cap.available is not fails
    assert cap.python_version and cap.qt_version
    if fails:
        assert 'no Metal adapter' in cap.reason


@pytest.mark.parametrize('platform', ['linux', 'win32'])
def test_unvalidated_platform(monkeypatch, platform):
    import sys
    from types import SimpleNamespace
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setitem(sys.modules, 'ingetrazo_render', SimpleNamespace())
    assert 'not validated' in rs._probe_local().reason


@pytest.mark.parametrize('outcome', ['ok', 'crash', 'timeout', 'malformed'])
def test_subprocess_boundary_and_cache(monkeypatch, outcome):
    from types import SimpleNamespace
    import subprocess
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        assert kwargs['timeout'] == 30
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(args[0], 30)
        return SimpleNamespace(returncode=-11 if outcome == 'crash' else 0,
                               stdout='{"available": true}' if outcome == 'ok' else '')
    monkeypatch.setattr(rs.subprocess, 'run', run)
    rs.capability.cache_clear()
    try:
        assert rs.capability().available is (outcome == 'ok')
        assert rs.capability() is rs.capability()
        assert len(calls) == 1
    finally:
        rs.capability.cache_clear()


def test_gl_window_without_render_crate(settings, monkeypatch):
    import sys
    from views.main_window import MainWindow
    monkeypatch.setitem(sys.modules, 'ingetrazo_render', None)
    monkeypatch.setenv('INGETRAZO_WGPU', '1')
    monkeypatch.setenv('INGETRAZO_AI_PORT', '0')
    monkeypatch.setattr(rs, 'capability', rs._probe_local)
    win = MainWindow()
    try:
        assert not win._doc._renderer_wgpu
        assert win._doc.stand_in is None
        assert 'render crate unavailable' in win._renderer_label.text()
        assert win.viewport.scene is not None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
