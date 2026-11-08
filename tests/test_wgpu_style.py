"""Style handoff must preserve document intent without creating a native device."""
from types import SimpleNamespace
import pytest
from core.style import Style, FACE_MODES
from views.wgpu_style import style_payload


@pytest.mark.parametrize('mode', FACE_MODES)
def test_modes_and_controls(mode):
    style = Style(face_mode=mode, ambient_occlusion=True, ao_distance=2.5,
                  edges=False, profiles=False, back_edges=True)
    result = style_payload(SimpleNamespace(display_style=style))
    assert result['face_mode'] == mode
    assert result['ambient_occlusion']
    assert result['ao_distance'] == 2.5
    assert not result['edges']
    assert not result['profiles']
    assert result['back_edges']


def test_override_back_tint_and_horizon():
    scene = SimpleNamespace(display_style=Style(), back_face_color=(.1, .2, .3))
    override = Style(sky=False, front_color=(.4, .5, .6))
    result = style_payload(scene, override, horizon=-3.25)
    assert result['back_color'] == (.1, .2, .3)
    assert result['front_color'] == [.4, .5, .6]
    assert result['horizon'] == -3.25
    assert not result['sky']
    override.back_color = (.7, .8, .9)
    assert style_payload(scene, override)['back_color'] == (.7, .8, .9)
    result['front_color'][0] = 0
    assert override.front_color == (.4, .5, .6)
