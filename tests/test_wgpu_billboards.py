"""Sprite UVs and resident face-me transforms agree with the GL pass."""
from types import SimpleNamespace
import importlib.util
import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from core import _native
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from views.wgpu_scene import pack_scene, _source_arrays
from views.wgpu_billboards import Billboards
from views.wgpu_axes import axes_state

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec('ingetrazo_render') is None or
    _native.available() is None or not hasattr(_native.available(), 'bake_scene'),
    reason='ingetrazo_core with bake_scene required (maturin develop --release)')


def figure(kind=True):
    mesh = Mesh()
    face = mesh.add_face([QVector3D(*p) for p in
                         [(-1.0093, -.6, 0), (-.2907, -.6, 0),
                          (-.2907, -.6, 1.7), (-1.0093, -.6, 1.7)]])
    face.attrs['texture'] = {'path': 'resources/components/ingeniero.png', 'sw': .7186, 'sh': 1.7}
    g = Group(mesh)
    g.billboard = kind
    return g


def test_fitted_uv_and_no_edges_only_for_sprite_prototype():
    sprite = figure()
    ordinary = Group(sprite.mesh)
    packed = pack_scene(Scene(groups=[sprite, ordinary]), texture_images=False)
    assert packed.edge_commands['count'].tolist() == [0, 8]
    assert packed.instances['info'][:, 0].tolist() == [0, 1]
    arrays = _source_arrays(sprite.mesh, billboard=True)
    points = arrays[0][arrays[1]]
    mapping = arrays[9][0].reshape(2, 2, 4)
    for side in mapping:
        uv = np.c_[points, np.ones(len(points))] @ side.T
        np.testing.assert_allclose(uv, [[0, 0], [1, 0], [1, 1], [0, 1]], atol=2e-7)
    planar = _source_arrays(sprite.mesh)[9][0]
    assert not np.array_equal(planar, arrays[9][0])
    assert sprite.mesh.faces[0].attrs['texture'] == {'path': 'resources/components/ingeniero.png', 'sw': .7186, 'sh': 1.7}


@pytest.mark.parametrize('kind', [True, 'mesh'])
@pytest.mark.parametrize('perspective', [False, True])
def test_world_faces_eye_without_reupload_or_tint_loss(kind, perspective):
    g = figure(kind)
    g.xform = QMatrix4x4()
    g.xform.translate(2, 3, 4)
    g.xform.rotate(35, 0, 0, 1)
    packed = pack_scene(Scene(groups=[g]), {g.uid: (.2, .3, .4)}, texture_images=False)
    original = packed.instances.copy()
    controller = Billboards(packed)
    camera = OrbitCamera()
    camera.perspective = perspective
    calls = []
    renderer = SimpleNamespace(set_instance_world=lambda ids, matrices: calls.append((ids, matrices.copy())))
    for yaw in (-1., .5, 2.):
        camera.yaw = yaw
        controller.update(camera, renderer)
        matrix = packed.instances['world'][0].T
        normal = np.linalg.inv(matrix[:3, :3]).T @ np.array([0., -1., 0.])
        anchor = controller.entries[0][0]
        direction = np.array(camera.eye().toTuple()) - (anchor if perspective else np.array(camera.target.toTuple()))
        np.testing.assert_allclose(normal[:2]/np.linalg.norm(normal[:2]), direction[:2]/np.linalg.norm(direction[:2]), atol=1e-6)
        np.testing.assert_array_equal(packed.instances['info'], original['info'])
        controller.update(camera, renderer)
    assert len(calls) == 3
    controller.restore()
    np.testing.assert_array_equal(packed.instances, original)


def test_mesh_billboard_preserves_its_material_mapping():
    g = figure('mesh')
    packed = pack_scene(Scene(groups=[g]), texture_images=False)
    ordinary = pack_scene(Scene(groups=[Group(g.mesh)]), texture_images=False)
    np.testing.assert_array_equal(packed.materials, ordinary.materials)
    assert packed.edge_commands['count'][0] == 0


def test_axes_state_toggle_context_and_export():
    scene, camera = Scene(), OrbitCamera()
    assert axes_state(scene, camera)[2]
    scene.show_axes = False
    assert not axes_state(scene, camera)[2]
    frame = QMatrix4x4()
    frame.translate(2, 3, 4)
    frame.rotate(45, 0, 0, 1)
    scene._edit_stack.append({'frame': frame})
    state = axes_state(scene, camera)
    assert state == (tuple(frame.data()), camera.distance*.008, True)
    source = SimpleNamespace(plano_style='plan', style_override=None)
    assert not axes_state(scene, camera, source)[2]
    source.plano_style = None
    source.style_override = object()
    assert not axes_state(scene, camera, source)[2]


def test_billboard_inference_uses_turned_geometry():
    from views.wgpu_inference import prepare, surface
    g = figure()
    packed = pack_scene(Scene(groups=[g]), texture_images=False)
    index = prepare(packed)
    controller = Billboards(packed)
    camera = OrbitCamera()
    camera.yaw = 1.2
    controller.update(camera, inference=index)
    center = QVector3D(*controller.entries[0][0]) + QVector3D(0, 0, .85)
    ray = (center-camera.eye()).normalized()
    hit = surface(index, 0, camera.eye(), ray)
    assert hit is not None
    assert (hit-center).length() < 1e-4


def test_nested_sprite_quad_matches_gl_and_survives_edit_context():
    from views.viewport import Viewport
    child = figure()
    parent = Group(Mesh())
    parent.children = [child]
    parent.xform = QMatrix4x4()
    parent.xform.translate(3, 4, 2)
    parent.xform.rotate(27, 0, 0, 1)
    scene = Scene(groups=[parent])
    vp = Viewport()
    vp.scene = scene
    try:
        for editing in (False, True):
            if editing:
                scene.begin_group_edit(parent)
            packed = pack_scene(scene, texture_images=False)
            controller = Billboards(packed)
            controller.update(vp.camera)
            proxy = next(p for p in vp._expand_placements(parent) if p.billboard)
            corners, _ = vp._billboard_quad(proxy)
            matrix = packed.instances['world'][controller.ids[0]].T
            points = np.array([v.position.toTuple() for v in child.mesh.vertices])
            actual = points @ matrix[:3, :3].T + matrix[:3, 3]
            expected = np.array([p.toTuple() for p in corners])
            # Mesh vertex ordering is not part of its public contract.
            for point in actual:
                assert np.min(np.linalg.norm(expected-point, axis=1)) < 2e-6
    finally:
        scene.end_group_edit()
        vp.close()


def test_shared_billboard_prototype_edit_rebuilds_without_affecting_ordinary():
    from views.wgpu_updates import InstanceUpdates
    sprite = figure()
    scene = Scene(groups=[sprite, Group(sprite.mesh)])
    packed = pack_scene(scene, texture_images=False)
    updates = InstanceUpdates(scene, packed)
    assert updates.diff(scene) is None


def test_capture_keeps_cutout_flag_and_camera_independence():
    from views.wgpu_sections import capture_rows
    g = figure()
    scene = Scene(groups=[g])
    packed = pack_scene(scene, texture_images=False)
    rows = capture_rows(packed, scene, {g.uid: (.2, .6, .9)})
    assert rows['info'][0, 2] == 8
    assert rows['info'][0, 3] != 0
    g.hidden = True
    rows = capture_rows(packed, scene, {})
    assert rows['info'][0, 2] == 9


def test_blank_discards_previous_billboard_row_cache():
    from views.wgpu_view import WgpuView
    view = WgpuView()
    try:
        view.set_scene(Scene(groups=[figure(), figure()]))
        assert len(view._billboards.ids) == 2
        view.blank()
        assert len(view._billboards.ids) == 0
        assert view._billboards.packed is view.packed
    finally:
        view.close()
