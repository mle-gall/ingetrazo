"""Empty-space zoom stays at view depth; high-resolution ticks stay fractional."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QVector3D as V, QWheelEvent
from core.camera import OrbitCamera
from views.viewport import Viewport


@pytest.mark.parametrize('slope', [-.001, 0., .001])
def test_background_near_horizon_uses_focal_depth(slope):
    camera = SimpleNamespace(target=V(0, 20, 10), eye=lambda: V(0, 0, 10))
    ray = V(0, 1, slope).normalized()
    vp = SimpleNamespace(camera=camera,
                         _pixel_to_ray=lambda *a: (camera.eye(), ray),
                         _depth_world_at=lambda *a: ('background', None))
    focus = Viewport._world_under_cursor(vp, 0, 0)
    assert focus.y() == pytest.approx(20)
    assert focus.z() == pytest.approx(10 + 20 * slope)
    assert (focus - camera.eye()).length() < 21


def test_real_surface_hit_keeps_its_actual_depth():
    hit = V(0, 200, 9)
    vp = SimpleNamespace(_pixel_to_ray=lambda *a: (V(0, 0, 10), V(0, 1, 0)),
                         _depth_world_at=lambda *a: ('hit', hit))
    assert Viewport._world_under_cursor(vp, 0, 0) is hit


def wheel(delta):
    return QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(),
                       QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                       Qt.ScrollUpdate, False)


def viewport():
    camera = OrbitCamera()
    camera.target = V(0, 0, 0)
    camera.distance = .02
    # The ticks carry a scroll phase, like a finger slide; the preference
    # keeps them zooming (views.trackpad_nav) so the fractions reach the
    # wheel's zoom.
    vp = SimpleNamespace(camera=camera, scene=SimpleNamespace(version=0),
                         _invert_wheel=False, _trackpad_slide="zoom",
                         update=lambda: None,
                         _zoom_out_step=lambda: 1.0,
                         _world_under_cursor=lambda *a: V(0, 0, 0))
    vp._zoom_at = lambda steps, pos: Viewport._zoom_at(vp, steps, pos)
    return vp


def test_many_fractional_ticks_do_not_each_receive_a_full_notch_floor():
    vp = viewport()
    for _ in range(120):
        Viewport.wheelEvent(vp, wheel(-1))
    assert vp.camera.distance == pytest.approx(1.02, abs=1e-5)
    notch = viewport()
    Viewport.wheelEvent(notch, wheel(-120))
    assert notch.camera.distance == pytest.approx(vp.camera.distance, abs=1e-5)


def test_zero_delta_does_not_pick_or_change_camera():
    vp = viewport()
    def unexpected(*args):
        pytest.fail('zero-delta event must not pick')
    vp._world_under_cursor = unexpected
    Viewport.wheelEvent(vp, wheel(0))
    assert vp.camera.distance == .02
