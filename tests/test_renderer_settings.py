"""Renderer selection persists while crash recovery covers presentation only."""
import pytest
from PySide6.QtCore import QSettings
from core import general_settings as gs, renderer_settings as rs


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv('INGETRAZO_WGPU', raising=False)
    monkeypatch.setattr(rs, '_checked', False)
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
