"""AO uses the same style values and diagnostic overrides in both views."""
from types import SimpleNamespace

from core.style import Style
from views.wgpu_style import style_payload


def test_ao_style_payload(monkeypatch):
    monkeypatch.delenv('INGETRAZO_AO', raising=False)
    style = Style(ambient_occlusion=True, ao_distance=2.5, ao_intensity=0.7)
    payload = style_payload(SimpleNamespace(display_style=style))
    assert payload['ambient_occlusion'] is True
    assert payload['ao_distance'] == 2.5
    assert payload['ao_intensity'] == 0.7
    assert payload['ao_samples'] == 16
    assert style_payload(None)['ambient_occlusion'] is False


def test_ao_environment_matches_gl(monkeypatch):
    monkeypatch.setenv('INGETRAZO_AO', '1')
    monkeypatch.setenv('INGETRAZO_AO_RADIUS', '0.8')
    monkeypatch.setenv('INGETRAZO_AO_INTENSITY', '1.2')
    monkeypatch.setenv('INGETRAZO_AO_SAMPLES', '32')
    payload = style_payload(None)
    assert (payload['ao_distance'], payload['ao_intensity'], payload['ao_samples']) == (0.8, 1.2, 32)
    monkeypatch.setenv('INGETRAZO_AO', '0')
    assert style_payload(None, Style(ambient_occlusion=True))['ambient_occlusion'] is False
