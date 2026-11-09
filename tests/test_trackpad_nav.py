# SPDX-License-Identifier: GPL-3.0-or-later
"""Trackpad and touch-screen navigation (#248).

A finger slide on the touch screen (the wheel events with a scroll phase
that macOS 27 synthesises on the primary pointer) orbits by default,
Shift pans, Cmd/Ctrl zooms; a two-finger slide on a real trackpad (its
own device id) zooms as it always did unless the preference says
otherwise; a pinch zooms toward the fingers through the wheel's zoom; a
slide and a pinch do not fight; the two-finger double tap frames the
model and goes back. A mouse wheel notch zooms as before.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import (QInputDevice, QNativeGestureEvent,
                           QPointingDevice, QWheelEvent)
from PySide6.QtWidgets import QApplication

from views import trackpad_nav

_app = QApplication.instance() or QApplication([])

CENTRE = QPointF(200, 150)

# What Qt makes of the screen's emulated events: the primary pointer, id 1.
TOUCHPAD = QPointingDevice(
    "trackpad or magic mouse", 1, QInputDevice.DeviceType.TouchPad,
    QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 2, 3)
# A real trackpad carries its own device id.
REAL_TRACKPAD = QPointingDevice(
    "trackpad or magic mouse", 504403158265495724, QInputDevice.DeviceType.TouchPad,
    QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 2, 3)
MOUSE = QPointingDevice(
    "mouse", 2, QInputDevice.DeviceType.Mouse,
    QPointingDevice.PointerType.Generic, QInputDevice.Capability.Position, 1, 3)


@pytest.fixture(autouse=True)
def _touch_emulation(monkeypatch):
    # The screen/trackpad distinction exists on macOS 27; test it everywhere.
    monkeypatch.setattr(trackpad_nav, "TOUCH_EMULATION", True)


@pytest.fixture
def vp():
    from views.viewport import Viewport
    view = Viewport(None)
    view.resize(400, 300)
    view._touch_slide = "orbit"
    view._trackpad_slide = "zoom"
    view._trackpad_inertia = True
    view._invert_orbit_y = False
    view._invert_wheel = False
    return view


def slide_event(dx, dy, phase=Qt.ScrollUpdate, mods=Qt.NoModifier,
                inverted=True, at=CENTRE, device=None):
    # Natural scrolling (the Mac default): the deltas follow the fingers.
    return QWheelEvent(at, at, QPoint(dx, dy), QPoint(dx * 8, dy * 8),
                       Qt.NoButton, mods, phase, inverted,
                       Qt.MouseEventSynthesizedBySystem,
                       device if device is not None else TOUCHPAD)


def slide(vp, dx, dy, **kw):
    QApplication.sendEvent(vp, slide_event(dx, dy, **kw))


def finger_slide(vp, dx, dy, steps=5, **kw):
    """A whole slide: begin, ``steps`` updates of (dx, dy), end."""
    slide(vp, 0, 0, phase=Qt.ScrollBegin, **kw)
    for _ in range(steps):
        slide(vp, dx, dy, **kw)
    slide(vp, 0, 0, phase=Qt.ScrollEnd, **kw)


def notch(vp, dy, at=CENTRE):
    QApplication.sendEvent(vp, QWheelEvent(
        at, at, QPoint(), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False, Qt.MouseEventNotSynthesized, MOUSE))


def pinch(vp, value, at=CENTRE):
    QApplication.sendEvent(vp, QNativeGestureEvent(
        Qt.ZoomNativeGesture, TOUCHPAD, 2, at, at, at, value, QPointF(), 0))


def gesture(vp, kind, value=0.0):
    QApplication.sendEvent(vp, QNativeGestureEvent(
        kind, TOUCHPAD, 2, CENTRE, CENTRE, CENTRE, value, QPointF(), 0))


def pose(vp):
    c = vp.camera
    return (c.yaw, c.pitch, c.distance, c.target.x(), c.target.y(), c.target.z())


# ---- pure readers -----------------------------------------------------------

def test_slide_pixels_follow_the_fingers_with_natural_scrolling():
    assert trackpad_nav.slide_pixels(slide_event(3, -4, inverted=True)) == (3, -4)


def test_slide_pixels_are_a_wheels_without_natural_scrolling():
    assert trackpad_nav.slide_pixels(slide_event(3, -4, inverted=False)) == (-3, 4)


def test_slide_pixels_fall_back_to_the_angle_without_pixel_deltas():
    ev = QWheelEvent(CENTRE, CENTRE, QPoint(), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.ScrollUpdate, True,
                     Qt.MouseEventNotSynthesized, TOUCHPAD)
    assert trackpad_nav.slide_pixels(ev) == (0, 15)


def test_a_mouse_notch_is_not_a_slide():
    ev = QWheelEvent(CENTRE, CENTRE, QPoint(), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False,
                     Qt.MouseEventNotSynthesized, MOUSE)
    assert not trackpad_nav.is_slide(ev)
    assert trackpad_nav.is_slide(slide_event(0, 1))


@pytest.mark.parametrize("mods,expected", [
    (Qt.NoModifier, "orbit"), (Qt.ShiftModifier, "pan"),
    (Qt.ControlModifier, "zoom"), (Qt.ShiftModifier | Qt.ControlModifier, "pan")])
def test_modifiers_pick_the_slide_mode(mods, expected):
    assert trackpad_nav.slide_mode(slide_event(0, 1, mods=mods), "orbit") == expected


def test_an_unknown_preference_zooms():
    assert trackpad_nav.slide_mode(slide_event(0, 1), "fly") == "zoom"


def test_the_screen_and_the_trackpad_are_told_apart_by_the_device():
    assert trackpad_nav.is_touch_screen(slide_event(0, 1))
    assert not trackpad_nav.is_touch_screen(slide_event(0, 1, device=REAL_TRACKPAD))
    assert not trackpad_nav.is_touch_screen(slide_event(0, 1, device=MOUSE))


def test_without_touch_emulation_every_slide_is_a_trackpads(monkeypatch):
    monkeypatch.setattr(trackpad_nav, "TOUCH_EMULATION", False)
    assert not trackpad_nav.is_touch_screen(slide_event(0, 1))


def test_a_pinch_of_one_notchs_scale_is_one_step():
    assert trackpad_nav.pinch_steps(1.0 / 0.9 - 1.0) == pytest.approx(1.0)
    assert trackpad_nav.pinch_steps(0.9 - 1.0) == pytest.approx(-1.0)
    assert trackpad_nav.pinch_steps(-1.0) is None


# ---- the slide ------------------------------------------------------------

def test_a_slide_orbits_and_keeps_the_distance(vp):
    yaw0, dist0 = vp.camera.yaw, vp.camera.distance
    finger_slide(vp, 10, 0)
    assert vp.camera.yaw != yaw0
    assert vp.camera.distance == pytest.approx(dist0)


def test_the_first_pixels_are_not_lost(vp):
    # Below the lock threshold nothing moves yet; once it is crossed the
    # whole slide so far is applied in one go.
    yaw0 = vp.camera.yaw
    slide(vp, 0, 0, phase=Qt.ScrollBegin)
    slide(vp, 2, 0)
    assert vp.camera.yaw == yaw0
    slide(vp, 2, 0)
    slide(vp, 2, 0)
    turned_in_3 = vp.camera.yaw - yaw0
    assert turned_in_3 != 0
    from views.viewport import Viewport
    other = Viewport(None)
    other.resize(400, 300)
    other._touch_slide = "orbit"
    other._trackpad_inertia = True
    other._invert_orbit_y = False
    finger_slide(other, 6, 0, steps=1)
    assert other.camera.yaw - yaw0 == pytest.approx(turned_in_3)


def test_a_slide_grabs_the_model_like_a_drag(vp):
    # A mouse drag of the same pixels through the middle button convention.
    from views.viewport import Viewport
    ref = Viewport(None)
    ref.resize(400, 300)
    pivot = ref._orbit_pivot_at(CENTRE.x(), CENTRE.y())
    ref.camera.orbit_about(pivot, 30, 10, ref.height())
    finger_slide(vp, 30, 10, steps=1)
    assert pose(vp) == pytest.approx(pose(ref))


def test_the_invert_orbit_preference_applies(vp):
    from views.viewport import Viewport
    ref = Viewport(None)
    ref.resize(400, 300)
    ref._touch_slide = "orbit"
    ref._invert_orbit_y = False
    finger_slide(ref, 0, 10, steps=1)
    vp._invert_orbit_y = True
    finger_slide(vp, 0, -10, steps=1)
    assert pose(vp) == pytest.approx(pose(ref))


def test_shift_pans_without_turning(vp):
    yaw0, pitch0 = vp.camera.yaw, vp.camera.pitch
    t0 = pose(vp)[3:]
    finger_slide(vp, 20, 0, mods=Qt.ShiftModifier)
    assert (vp.camera.yaw, vp.camera.pitch) == (yaw0, pitch0)
    assert pose(vp)[3:] != pytest.approx(t0)


def test_ctrl_zooms_like_the_wheel(vp):
    d0 = vp.camera.distance
    # With natural scrolling the deltas follow the fingers: up is -y.
    finger_slide(vp, 0, -15, mods=Qt.ControlModifier)      # fingers up: in
    assert vp.camera.distance < d0


def test_the_zoom_preference_keeps_the_old_feel(vp):
    vp._touch_slide = "zoom"
    d0, yaw0 = vp.camera.distance, vp.camera.yaw
    finger_slide(vp, 0, -15)                                # fingers up: in
    assert vp.camera.distance < d0
    assert vp.camera.yaw == yaw0


def test_a_trackpad_slide_zooms_as_before_by_default(vp):
    d0, yaw0 = vp.camera.distance, vp.camera.yaw
    finger_slide(vp, 0, -15, device=REAL_TRACKPAD)          # fingers up: in
    assert vp.camera.distance < d0
    assert vp.camera.yaw == yaw0


def test_the_trackpad_can_be_told_to_orbit(vp):
    vp._trackpad_slide = "orbit"
    yaw0, d0 = vp.camera.yaw, vp.camera.distance
    finger_slide(vp, 10, 0, device=REAL_TRACKPAD)
    assert vp.camera.yaw != yaw0
    assert vp.camera.distance == pytest.approx(d0)


def test_the_pan_preference_pans(vp):
    vp._touch_slide = "pan"
    t0 = pose(vp)[3:]
    finger_slide(vp, 20, 0)
    assert vp.camera.yaw == pytest.approx(pose(vp)[0])
    assert pose(vp)[3:] != pytest.approx(t0)


def test_momentum_keeps_turning_with_inertia_on(vp):
    finger_slide(vp, 10, 0)
    yaw1 = vp.camera.yaw
    slide(vp, 6, 0, phase=Qt.ScrollMomentum)
    assert vp.camera.yaw != yaw1


def test_momentum_is_dropped_with_inertia_off(vp):
    vp._trackpad_inertia = False
    finger_slide(vp, 10, 0)
    yaw1 = vp.camera.yaw
    slide(vp, 6, 0, phase=Qt.ScrollMomentum)
    slide(vp, 6, 0, phase=Qt.ScrollMomentum)
    assert vp.camera.yaw == yaw1


def test_a_new_slide_picks_its_pivot_again(vp):
    finger_slide(vp, 10, 0)
    first = trackpad_nav.gesture(vp).pivot
    assert first is not None
    slide(vp, 0, 0, phase=Qt.ScrollBegin)
    assert trackpad_nav.gesture(vp).pivot is None


def test_a_mouse_notch_still_zooms(vp):
    d0, yaw0 = vp.camera.distance, vp.camera.yaw
    notch(vp, 120)
    assert vp.camera.distance < d0
    assert vp.camera.yaw == yaw0


# ---- the pinch ------------------------------------------------------------

def test_spreading_the_fingers_zooms_in_and_pinching_zooms_out(vp):
    d0 = vp.camera.distance
    pinch(vp, 0.1)
    assert vp.camera.distance < d0
    d1 = vp.camera.distance
    gesture(vp, Qt.EndNativeGesture)
    pinch(vp, -0.1)
    assert vp.camera.distance > d1


def test_a_pinch_of_one_notchs_scale_zooms_one_notch(vp):
    from views.viewport import Viewport
    wheel = Viewport(None)
    wheel.resize(400, 300)
    wheel._invert_wheel = False       # whatever another test left in QSettings
    notch(wheel, 120)
    pinch(vp, 1.0 / 0.9 - 1.0)
    assert vp.camera.distance == pytest.approx(wheel.camera.distance, rel=1e-6)


def test_tiny_pinch_steps_add_up_to_the_same_zoom(vp):
    # The first steps wait for the lock, then arrive all at once: nothing
    # of the gesture is lost.
    from views.viewport import Viewport
    one = Viewport(None)
    one.resize(400, 300)
    pinch(one, 1.0 / 0.9 - 1.0)
    for _ in range(20):
        pinch(vp, (1.0 / 0.9) ** (1 / 20) - 1.0)
    assert vp.camera.distance == pytest.approx(one.camera.distance, rel=1e-4)


def test_the_point_under_the_fingers_stays_put(vp):
    at = QPointF(260, 110)
    focus = vp._world_under_cursor(at.x(), at.y())
    assert focus is not None
    d0 = vp.camera.distance
    for _ in range(10):
        pinch(vp, 0.04, at)
    assert vp.camera.distance < d0 * 0.75
    px = vp._world_to_pixel(focus)
    assert px is not None
    assert px[0] == pytest.approx(at.x(), abs=0.5)
    assert px[1] == pytest.approx(at.y(), abs=0.5)


def test_the_wheel_preference_does_not_flip_the_pinch(vp):
    vp._invert_wheel = True
    d0 = vp.camera.distance
    pinch(vp, 0.1)
    assert vp.camera.distance < d0


def test_a_pinch_in_progress_drops_the_slide_underneath(vp):
    pinch(vp, 0.1)
    p1 = pose(vp)
    slide(vp, 10, 0)                       # the fingers drifted sideways
    slide(vp, 10, 0)
    assert pose(vp) == p1


def test_a_slide_in_progress_drops_the_pinch_underneath(vp):
    finger_slide(vp, 10, 0)
    slide(vp, 0, 0, phase=Qt.ScrollBegin)
    slide(vp, 10, 0)
    d1 = vp.camera.distance
    pinch(vp, 0.2)                         # the fingers spread a little
    assert vp.camera.distance == d1


def test_lifting_the_fingers_frees_the_gesture(vp):
    pinch(vp, 0.1)
    gesture(vp, Qt.EndNativeGesture)
    yaw0 = vp.camera.yaw
    finger_slide(vp, 10, 0)
    assert vp.camera.yaw != yaw0


def test_a_rotation_is_taken_and_changes_nothing(vp):
    p0 = pose(vp)
    gesture(vp, Qt.RotateNativeGesture, 15.0)
    assert pose(vp) == p0


# ---- smart zoom (two-finger double tap) ------------------------------------

def smart_zoom(vp):
    gesture(vp, Qt.SmartZoomNativeGesture, 1.0)


def test_a_smart_zoom_asks_the_window(vp):
    seen = []
    vp.smartZoomRequested.connect(lambda: seen.append(1))
    smart_zoom(vp)
    assert seen == [1]


class _Window:
    """The two MainWindow methods under test, over a real viewport, with
    Zoom Extents framing a fixed box."""

    def __init__(self, vp):
        from types import MethodType

        from PySide6.QtGui import QVector3D
        from views.main_window import MainWindow
        self.viewport = vp
        self._camera_pose = MethodType(MainWindow._camera_pose, self)
        self._on_smart_zoom = MethodType(MainWindow._on_smart_zoom, self)
        self.box = (QVector3D(0, 0, 0), QVector3D(20, 10, 6))
        vp.smartZoomRequested.connect(self._on_smart_zoom)

    def _on_zoom_extents(self):
        self.viewport.camera.fit_box(*self.box)


def test_a_double_tap_frames_the_model_and_a_second_goes_back(vp):
    win = _Window(vp)
    vp.camera.distance = 2.0
    start = win._camera_pose()
    smart_zoom(vp)
    framed = win._camera_pose()
    assert framed != start
    smart_zoom(vp)
    assert win._camera_pose() == pytest.approx(start)


def test_after_moving_the_view_a_double_tap_frames_again(vp):
    win = _Window(vp)
    vp.camera.distance = 2.0
    start = win._camera_pose()
    smart_zoom(vp)
    framed = win._camera_pose()
    pinch(vp, 0.2)
    moved = win._camera_pose()
    smart_zoom(vp)
    assert win._camera_pose() == pytest.approx(framed)
    assert win._camera_pose() != pytest.approx(start)
    assert win._camera_pose() != pytest.approx(moved)


# ---- the Metal view -------------------------------------------------------

def test_the_metal_view_orbits_and_pinches_too():
    from types import SimpleNamespace

    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import Group
    from core.mesh import Mesh
    from core.scene import Scene
    from views.viewport import Viewport
    from views.wgpu_inference import prepare
    from views.wgpu_scene import pack_scene
    from views.wgpu_view import WgpuView

    scene = Scene()
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                   QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    group = Group(mesh, name="placed")
    group.xform = QMatrix4x4()
    scene.groups.append(group)
    source = Viewport(None)
    source.resize(400, 300)
    source._touch_slide = "orbit"
    source._trackpad_inertia = True
    v = WgpuView()
    v.resize(400, 300)
    v.source_viewport = source
    v.camera = source.camera
    v.scene = scene
    v.packed = pack_scene(scene)
    v.uid_rows = {uid: [i] for i, uid in enumerate(v.packed.uids)}
    v.camera.target = QVector3D(1, 1, 0)
    v.camera.distance = 8
    v.camera.aspect = 400 / 300
    v.inference_index = prepare(v.packed)
    v.renderer = SimpleNamespace(set_highlight=lambda *a: None,
                                 set_rest=lambda *a: None,
                                 pick=lambda *a: 0, pick_rect=lambda *a: [0])
    try:
        yaw0, d0 = v.camera.yaw, v.camera.distance
        finger_slide(v, 10, 0)
        assert v.camera.yaw != yaw0
        assert v.camera.distance == pytest.approx(d0)
        gesture(v, Qt.EndNativeGesture)
        pinch(v, 0.1)
        assert v.camera.distance < d0
        seen = []
        source.smartZoomRequested.connect(lambda: seen.append(1))
        smart_zoom(v)
        assert seen == [1]
    finally:
        v.renderer = None
        v.close()
