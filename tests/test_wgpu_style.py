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


def test_profile_width_and_dash_defaults():
    style = Style(profiles=True, back_edges=True, edge_color=(.2, .3, .4))
    style.profile_width = 3.0
    payload = style_payload(SimpleNamespace(display_style=style))
    assert payload['profile_width'] == 3.0
    assert payload['edge_color'] == [.2, .3, .4]
    assert payload['dash_width'] == 4.0
    assert style_payload(SimpleNamespace(display_style=style), scale=2)['dash_width'] == 8.0
    assert style_payload(SimpleNamespace(display_style=Style()))['profile_width'] == 1.0


def test_section_plane_keeps_gl_half_space_and_resets():
    from core.scene import Scene
    from core.section import SectionPlane
    from PySide6.QtGui import QVector3D
    scene = Scene()
    plane = SectionPlane(QVector3D(2, 3, 4), QVector3D(1, 0, 0), active=True)
    scene.section_planes.append(plane)
    assert style_payload(scene)['section_plane'] == (-1., 0., 0., 2.)
    plane.normal = QVector3D(-1, 0, 0)
    assert style_payload(scene)['section_plane'] == (1., 0., 0., -2.)
    scene.show_section_cuts = False
    assert style_payload(scene)['section_plane'] == (0., 0., 0., 0.)
