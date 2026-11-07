"""Hidden Geometry reveals smooth seams without changing normals or solids."""
import pytest
import numpy as np
from PySide6.QtGui import QVector3D as V, QMatrix4x4
from core.mesh import Mesh
from core.group import Group
from tests.test_rendering_surface_regressions import viewport, pixels
from tests.test_viewport_smooth_shading import _cylinder


@pytest.mark.parametrize('placement', ['loose', 'group', 'instance', 'nested'])
def test_hidden_geometry_reveals_soft_seams(viewport, placement):
    vp = viewport
    mesh = _cylinder(vp.scene.mesh if placement == 'loose' else Mesh())
    if placement != 'loose':
        g = Group(mesh, 'smooth tube')
        if placement in ('instance', 'nested'):
            g.xform = QMatrix4x4()
            g.xform.translate(.2, 0, 0)
        if placement == "nested":
            parent_mesh = Mesh()
            child = g
            g = Group(parent_mesh, "container")
            g.adopt([child])
            g.xform = QMatrix4x4()
            g.xform.rotate(25, 0, 0, 1)
        vp.scene.groups.append(g)
    vp.scene.show_axes = False
    vp.scene.display_style.profiles = False
    vp.scene.version += 1
    vp.camera.target = V(0, 0, 1)
    vp.camera.distance = 5
    vp.camera.pitch = .2
    vp.camera.yaw = .7
    before_flags = [e.soft for e in mesh.edges]
    off = pixels(vp.render_image(480, 360, overlays=False))
    content = vp.scene.content_version
    vp.window()._set_hidden_view('show_hidden_geometry', True)
    assert vp.scene.content_version == content
    on = pixels(vp.render_image(480, 360, overlays=False))
    # Thousands of smooth-wall pixels remain identical, with dashed seams
    # added in front. The source flags (and hence smoothing) stay unchanged.
    darker = np.any(on < off - 20, axis=2)
    assert np.count_nonzero(darker) > 50
    assert np.count_nonzero(darker) < 12000
    assert [e.soft for e in mesh.edges] == before_flags
    cached = vp._hidden_edge_draw(mesh)
    assert cached['count'] == 2 * sum(e.soft or e.hidden for e in mesh.edges)
    vp.window()._set_hidden_view('show_hidden_geometry', False)
    restored = pixels(vp.render_image(480, 360, overlays=False))
    assert np.array_equal(off, restored)
    vp.window()._set_hidden_view('show_hidden_geometry', True)
    vp.render_image(480, 360, overlays=False)
    assert vp._hidden_edge_draw(mesh) is cached
