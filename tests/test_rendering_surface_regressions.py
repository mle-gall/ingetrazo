"""Tube triangulation, transformed smooth instances and thin back materials."""
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V, QMatrix4x4, QImage
from PySide6.QtWidgets import QApplication
from core.mesh import Mesh
from core.group import Group, transformed_mesh
from formats.meshexport import SmoothNormals
from tests.test_viewport_smooth_shading import _cylinder, _stub
from core.scene import Scene

_app = QApplication.instance() or QApplication([])


def test_splitting_one_tube_panel_does_not_move_its_corner_normals():
    m = Mesh()
    n = 12
    ring = [V(math.cos(i * 2 * math.pi / n), math.sin(i * 2 * math.pi / n), 0)
            for i in range(n)]
    top = [p + V(0, 0, 2) for p in ring]
    for i in range(n):
        j = (i + 1) % n
        if i == 0:
            m.add_face([ring[i], ring[j], top[j]])
            m.add_face([ring[i], top[j], top[i]])
        else:
            m.add_face([ring[i], ring[j], top[j], top[i]])
    for e in m.edges:
        e.soft = len(e.faces) == 2
    smooth = SmoothNormals()
    for f in m.faces:
        for pos, normal in smooth.corners(f).items():
            assert np.allclose(normal.toTuple(), (pos[0], pos[1], 0), atol=1e-5)


def test_rotating_smooth_cpu_chunk_matches_baking_world_geometry():
    vp = _stub(Scene())
    mesh = _cylinder(Mesh())
    xf = QMatrix4x4()
    xf.rotate(43, 1, 0, 0)
    instance = Group(mesh, 'instance')
    instance.xform = xf
    placed = Group(transformed_mesh(mesh, xf), 'placed')
    got = np.frombuffer(vp._instance_chunk(instance)['vcol'], np.float32).reshape(-1, 6)
    want = np.frombuffer(vp._group_chunk(placed)['vcol'], np.float32).reshape(-1, 6)
    # Side triangles are smooth; caps retain their quantised flat shade.
    assert np.allclose(got[:72], want[:72], atol=1e-5)


def pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), image.bytesPerLine())[:, :image.width()*4].copy().reshape(
            image.height(), image.width(), 4)[..., :3].astype(int)


@pytest.fixture
def viewport():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    try:
        vp = win.viewport
        if not vp.isValid() or getattr(vp, '_gl', None) is None:
            pytest.skip('requires OpenGL')
        yield vp
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_thin_plate_reverse_material_does_not_show_through(viewport):
    vp = viewport
    m = vp.scene.mesh
    front = [V(-10, -10, 0), V(10, -10, 0), V(10, 10, 0), V(-10, 10, 0)]
    m.add_face(front)
    back = m.add_face([p - V(0, 0, .001) for p in reversed(front)])
    back.attrs['back'] = {'color': (1., 0., 0.)}
    cam = vp.camera
    cam.target, cam.distance = V(0, 0, 0), 20.
    cam.yaw, cam.pitch = math.radians(20), math.radians(5)
    vp.scene.version += 1
    red = pixels(vp.render_image(400, 300, overlays=False))
    back.attrs['back']['color'] = (0., 1., 0.)
    vp.scene.version += 1
    green = pixels(vp.render_image(400, 300, overlays=False))
    # A hidden reverse material must not affect the middle of the front.
    assert np.max(np.abs(red[130:170, 160:240] - green[130:170, 160:240])) <= 2


def test_smooth_gpu_cylinder_is_invariant_under_one_panel_rotation(viewport):
    vp = viewport
    mesh = _cylinder(Mesh())
    group = Group(mesh, 'tube')
    group.xform = QMatrix4x4()
    vp.scene.groups.append(group)
    vp.camera.target, vp.camera.distance = V(0, 0, 1), 7.
    vp.camera.yaw, vp.camera.pitch = math.radians(25), math.radians(10)
    vp.scene.version += 1
    assert vp._instanced_eligible(group)
    a = pixels(vp.render_image(400, 300, overlays=False))
    group.xform.rotate(30, 0, 0, 1)
    vp.scene.version += 1
    b = pixels(vp.render_image(400, 300, overlays=False))
    assert np.percentile(np.abs(a-b), 99) <= 2


def test_identical_prototype_batching_preserves_smooth_mirrored_render(viewport, monkeypatch):
    vp = viewport
    for i in range(6):
        g = Group(_cylinder(Mesh()), f'independent tube {i}')
        g.xform = QMatrix4x4()
        g.xform.translate((i % 3) * 3 - 3, (i // 3) * 3, 0)
        g.xform.rotate(20 * i, 1, 0, 0)
        if i % 2:
            g.xform.scale(-1, 1, 1)
        vp.scene.groups.append(g)
    vp.camera.target, vp.camera.distance = V(0, 1.5, 1), 16.
    vp.scene.version += 1
    combined = pixels(vp.render_image(600, 400, overlays=False))
    assert len(vp._frame_instanced) == 2
    monkeypatch.setattr(vp, '_inst_draw_codes', lambda p: (p[4], p[5], p[7]))
    vp._inst_frame_memo = {}
    vp.scene.version += 1
    separate = pixels(vp.render_image(600, 400, overlays=False))
    assert len(vp._frame_instanced) == 6
    assert np.percentile(np.abs(combined - separate), 99.9) <= 2


def test_command_chunks_match_one_continuous_pass(viewport, monkeypatch):
    vp = viewport
    for i in range(48):
        g = Group(_cylinder(Mesh()), f'tube {i}')
        g.xform = QMatrix4x4()
        g.xform.translate((i % 8) * 3, (i // 8) * 3, 0)
        g.material = {'color': [0.2 + i / 100, 0.4, 0.7]}
        vp.scene.groups.append(g)
    vp.camera.target, vp.camera.distance = V(10, 7, 1), 40.
    vp.scene.version += 1
    chunks = pixels(vp.render_image(600, 400, overlays=False))
    assert len(vp._inst_draw_chunks(vp._frame_instanced)) >= 3
    if vp._gl_replay() is not None:
        assert vp._lean_faces_rec_merged is not None
    monkeypatch.setattr(vp, '_draw_instanced_faces_lean', vp._draw_instanced_faces_chunk)
    monkeypatch.setattr(vp, '_draw_instanced_edges_lean', vp._draw_instanced_edges_chunk)
    vp._lean_faces_rec = vp._lean_edges_rec = None
    vp.scene.version += 1
    continuous = pixels(vp.render_image(600, 400, overlays=False))
    assert np.percentile(np.abs(chunks-continuous), 99.99) <= 2
