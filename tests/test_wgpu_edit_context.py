"""Nested edit context, live preferences and native flag lifetime."""
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.group import Group
from core.mesh import Mesh
from views.viewport import Viewport, edit_fade_color
from views.wgpu_view import WgpuView
from views.wgpu_scene import pack_scene
from views.wgpu_edit_context import rest_rows
from views.wgpu_style import style_payload

app = QApplication.instance() or QApplication([])


def group(name):
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(0, 1, 1)])
    return Group(mesh, name=name)


@pytest.fixture
def context():
    a, b, sibling, outside = [group(n) for n in ('parent', 'inner', 'sibling', 'outside')]
    a.adopt([b, sibling])
    scene = Scene(groups=[a, outside])
    source = Viewport()
    source.scene = scene
    source._edit_rest_mode = 'fade'
    source._edit_rest_fade_strength = .7
    view = WgpuView()
    view.resize(800, 600)
    source.resize(800, 600)
    view.scene = scene
    view.source_viewport = source
    view.camera = source.camera
    view.packed = pack_scene(scene)
    calls = []
    view.renderer = SimpleNamespace(set_rest=lambda *args: calls.append(args),
                                    pick=lambda *args: 0,
                                    pick_rect=lambda *args: list(range(len(view.packed.groups))))
    yield view, source, a, b, sibling, outside, calls
    view.renderer = None
    view.close()
    source.close()


def test_innermost_subtree_and_billboards(context):
    view, _, a, b, sibling, outside, _ = context
    outside.billboard = 'mesh'
    groups = [None, a, b, sibling, outside]
    assert rest_rows(groups, None) == []
    assert rest_rows(groups, a) == [0, 4]
    assert rest_rows(groups, b) == [0, 1, 3, 4]


def test_mode_switch_writes_once_and_hide_filters_picks(context):
    view, source, a, b, _, _, calls = context
    view.scene.begin_group_edit(a)
    view.scene.begin_group_edit(b)
    view.sync_edit_context()
    view.sync_edit_context()
    assert len(calls) == 1
    source._edit_rest_fade_strength = .2
    view.scene.select([a])
    view.sync_edit_context()
    assert len(calls) == 1
    source._edit_rest_mode = 'hide'
    view.sync_edit_context()
    view.sync_edit_context()
    assert len(calls) == 2
    rest = calls[-1][0]
    view.renderer.pick = lambda *args: rest[0]
    assert view.pick_row(10, 10) is None
    assert all(view.packed.groups[r] is b for r in view.rect_rows(0, 0, 100, 100))
    source._edit_rest_mode = 'none'
    view.sync_edit_context()
    assert not np.any(view.packed.instances['info'][:, 2] & 192)
    assert len(calls) == 3


@pytest.mark.parametrize('background', [(.94, .94, .94), (.08, .08, .08)])
def test_style_fade(background):
    scene = Scene()
    scene.display_style.background = background
    payload = style_payload(scene, edit_rest_fade=.73)
    assert payload['fade'] == .73
    assert payload['fade_color'] == edit_fade_color(background)
    assert np.allclose(payload['fade_color'], .5 * np.array(background) + .275)


def test_box_matches_gl_corners_and_hit_helper(context):
    view, source, a, b, _, _, _ = context
    view.scene.begin_group_edit(a)
    view.scene.begin_group_edit(b)
    actual, expected = view._edit_group_box_corners(), source._edit_group_box_corners()
    assert actual == expected
    assert len(view._edit_box_primitives()) == 12
    for x, y in [(0, 0), (400, 300), (799, 599)]:
        assert view.edit_group_box_contains_pixel(x, y) == source.edit_group_box_contains_pixel(x, y)


def test_shader_rest_bits_are_preserved_and_shared():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'rust/ingetrazo_render/src'
    assert '(i.info.z & 129u)' in (root / 'shader.wgsl').read_text()
    assert 'face_pixel(i, front)' in (root / 'xray.wgsl').read_text()
    assert 'style.fade.rgb, style.fade.a' in (root / 'shading.wgsl').read_text()


def test_hidden_row_never_reaches_inference(context):
    from views.wgpu_inference import snap
    view, source, a, b, _, _, calls = context
    view.scene.begin_group_edit(a)
    view.scene.begin_group_edit(b)
    source._edit_rest_mode = 'hide'
    view.sync_edit_context()
    # A stale hover ID must be rejected before touching the native index.
    assert snap(None, calls[-1][0][0], view, 10, 10) is None
    view.packed = pack_scene(view.scene)
    view.sync_edit_context()
    assert len(calls) == 2
    assert np.count_nonzero(view.packed.instances['info'][:, 2] & 128) == len(calls[-1][0])


def test_empty_click_uses_box_to_leave_one_level(context):
    from PySide6.QtCore import Qt
    view, source, a, b, _, _, _ = context
    view.scene.begin_group_edit(a)
    view.scene.begin_group_edit(b)
    source.end_one_group_edit = view.scene.end_one_group_edit
    assert not view._leave_edit_on_empty_click(-100, -100, Qt.ShiftModifier)
    assert view.scene.edit_group is b
    assert view._leave_edit_on_empty_click(-100, -100, Qt.NoModifier)
    assert view.scene.edit_group is a
