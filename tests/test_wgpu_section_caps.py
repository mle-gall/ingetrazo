"""GL topology and saved-frame cap state reach the native pass."""
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.section import SectionPlane
from core.camera import OrbitCamera
from views.wgpu_scene import pack_scene
from views.wgpu_sections import geometry, capture_rows
from tests.test_section_fill import _box


def fixture():
    scene = Scene()
    _box(scene.loose_mesh, 0, 0, 0, 2, 3, 2)
    scene.section_planes = [SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1), active=True)]
    return scene, SimpleNamespace(packed=pack_scene(scene)), OrbitCamera()


def test_cap_area_color_cache_and_xray_boundary():
    scene, view, camera = fixture()
    style = scene.display_style
    style.section_fill_color = (.8, .2, .1)
    data = geometry(view, scene, style, camera, 600)
    assert data is geometry(view, scene, style, camera, 600)
    vertices = data.view('<f4').reshape(-1, 6)
    cap = vertices[np.all(np.isclose(vertices[:, 3:], style.section_fill_color), axis=1), :3].reshape(-1, 3, 3)
    assert np.linalg.norm(np.cross(cap[:, 1]-cap[:, 0], cap[:, 2]-cap[:, 0]), axis=1).sum()/2 == pytest.approx(6)
    style.face_mode = 'xray'
    boundary = geometry(view, scene, style, camera, 600).view('<f4').reshape(-1, 6)
    assert len(boundary) > 0
    assert np.allclose(boundary[:, 3:], style.edge_color)


def test_hatch_master_switch_and_hidden_capture_rows():
    scene, view, camera = fixture()
    scene.active_section().fill = {'pattern': 'cross', 'spacing': .5}
    hatched = geometry(view, scene, scene.display_style, camera, 600)
    scene.display_style.section_fill = False
    assert len(geometry(view, scene, scene.display_style, camera, 600)) < len(hatched)
    rows = capture_rows(view.packed, scene, {})
    rows['info'][:, 2] = 1
    assert not len(geometry(view, scene, scene.display_style, camera, 600, rows))


def test_offscreen_supplies_cap_and_restores_after_failure():
    from views.wgpu_view import WgpuView
    scene, model, camera = fixture()
    view = WgpuView()
    view.packed = model.packed
    view.source_viewport = SimpleNamespace(scene=scene, camera=camera, plano_style=None, style_override=None,
        _effective_style=lambda: scene.display_style, _horizon_ndc_y=lambda m: 2.)
    previous = np.empty(0, np.uint8)
    view._section_uploaded = previous
    class Renderer:
        def set_axes(self, frame, spacing, visible):
            self.axes = (frame, spacing, visible)
        def set_section_geometry(self, data):
            self.data = data
        def render_image(self, w, h, v, p, payload, rows):
            assert len(self.data) > 0
            assert payload['section_fill_color'] == list(scene.display_style.section_fill_color)
            assert len(rows) == model.packed.instances.nbytes
            raise RuntimeError('readback failed')
    view.renderer = Renderer()
    with pytest.raises(RuntimeError, match='readback failed'):
        view.render_image(600, 400)
    assert view.renderer.data is previous
    view.close()


def test_saved_visibility_navigator_and_tint_do_not_modify_resident_rows():
    from core.group import Group
    from core.mesh import Mesh
    mesh = Mesh()
    _box(mesh, 0, 0, 0, 2, 3, 2)
    groups = [Group(mesh), Group(mesh)]
    scene = Scene(groups=groups)
    packed = pack_scene(scene)
    before = packed.instances.copy()
    groups[0].hidden = True
    rows = capture_rows(packed, scene, {groups[1].uid: (1., 0., 0.)})
    assert rows['info'][0, 2] & 1
    assert rows['info'][1, 3] == 0xff0000ff
    groups[0].hidden = False
    scene._navigator_allowed = {groups[0].uid}
    rows = capture_rows(packed, scene, {})
    assert rows['info'][1, 2] & 1
    np.testing.assert_array_equal(packed.instances, before)
