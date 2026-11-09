# SPDX-License-Identifier: GPL-3.0-or-later
"""Trackpad and touch-screen navigation, shared by the GL and Metal views.

A trackpad (and, on macOS 27, a finger on the touch screen of a program
that is not touch-native: the system emulates a trackpad for it) reaches
the viewport as two kinds of events:

* a **slide** -- the wheel events with a scroll phase that a two-finger
  slide on the trackpad, or one finger on the screen, produces, dozens a
  second with pixel deltas;
* **native gestures** -- a pinch (``ZoomNativeGesture``, the change of
  scale per step), a rotation, and the two-finger double tap
  (``SmartZoomNativeGesture``).

Until now the slide zoomed like a wheel and the gestures were dropped: on
a Mac trackpad a pinch did nothing (#248), and on the touch screen a
finger slid across the view zoomed it. Here a slide on the **touch
screen** orbits the view around the point it started on, a slide on the
**trackpad** keeps zooming as it always did (Preferences can make either
orbit, pan or zoom), Shift turns a slide into a pan and Cmd/Ctrl into the
zoom, the pinch zooms toward the fingers through the same zoom as the
wheel, and the smart zoom asks the window to frame the model.

The two are told apart by the device: a real trackpad's wheel events
carry the trackpad's own device id, the emulated ones of the screen come
from the primary pointer (device id 1) -- measured on Maxence's MacBook
Pro, 2026-11-09, both named "trackpad or magic mouse" by Qt otherwise.

A slide and a pinch arrive mixed: the fingers of a slide drift apart a
little, and a pinch wanders. The first of the two to move past a small
threshold takes the gesture and the other is dropped until the fingers
lift (``IDLE_RESET_S`` without events, or an end-of-gesture event).

The functions take the *view* (a :class:`views.viewport.Viewport` or a
:class:`views.wgpu_view.WgpuView`) and read what they need from it:
``camera``, ``height()``, ``_orbit_pivot_at``, ``_zoom_at`` and the
``_invert_orbit_y`` / ``_touch_slide`` / ``_trackpad_slide`` /
``_trackpad_inertia`` preferences, looked up on the view, then on its
``source_viewport``.
"""
from __future__ import annotations

import math
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QInputDevice, QVector3D

#: What a slide does: ``orbit`` | ``pan`` | ``zoom``. A finger on the touch
#: screen orbits; two fingers on the trackpad zoom, as before 0.6.1.
SLIDE_MODES = ("orbit", "pan", "zoom")
DEFAULT_TOUCH_SLIDE = "orbit"
DEFAULT_SLIDE = "zoom"

#: Only macOS 27 hands the touch screen to a program as a trackpad; the
#: id of the pointer those emulated events arrive on (a real trackpad's
#: events carry its own, large, device id). Tests toggle the first.
TOUCH_EMULATION = sys.platform == "darwin"
TOUCH_SCREEN_IDS = (1,)

#: A pinch takes the gesture once the scale has changed by this share.
PINCH_LOCK_SHARE = 0.03
#: A slide takes the gesture once the fingers have moved this far.
SLIDE_LOCK_PX = 6.0
#: No event for this long: the fingers lifted, the next event starts over.
IDLE_RESET_S = 0.35

#: A wheel notch is ×1/0.9 (``OrbitCamera.zoom``).
_NOTCH = -math.log(0.9)


# ---- preferences -----------------------------------------------------------

def load_slide_mode() -> str:
    """The trackpad's two-finger slide."""
    from PySide6.QtCore import QSettings
    mode = str(QSettings().value("nav/trackpad_slide", DEFAULT_SLIDE)).lower()
    return mode if mode in SLIDE_MODES else DEFAULT_SLIDE


def load_touch_slide() -> str:
    """A finger's slide on the touch screen."""
    from PySide6.QtCore import QSettings
    mode = str(QSettings().value("nav/touch_slide", DEFAULT_TOUCH_SLIDE)).lower()
    return mode if mode in SLIDE_MODES else DEFAULT_TOUCH_SLIDE


def load_inertia() -> bool:
    """Whether the view keeps turning after the fingers lift (the momentum
    events macOS sends). On by default: it is what makes a trackpad feel
    smooth (#248)."""
    from PySide6.QtCore import QSettings
    return str(QSettings().value("nav/trackpad_inertia", "1")) != "0"


def _pref(view, attr: str, loader):
    value = getattr(view, attr, None)
    if value is None:
        source = getattr(view, "source_viewport", None)
        value = getattr(source, attr, None) if source is not None else None
    if value is None:
        value = loader()
    return value


# ---- pure event readers ----------------------------------------------------

def is_slide(ev) -> bool:
    """A wheel event that is a finger slide (trackpad or touch screen),
    not a notch of a mouse wheel: it carries a scroll phase, or comes
    from a touch device."""
    if ev.phase() != Qt.NoScrollPhase:
        return True
    device = ev.device()
    return device is not None and device.type() in (
        QInputDevice.DeviceType.TouchPad, QInputDevice.DeviceType.TouchScreen)


def is_touch_screen(ev) -> bool:
    """A slide whose wheel events the system synthesised for a finger on
    the touch screen, as opposed to a trackpad's (see the module doc)."""
    if not TOUCH_EMULATION:
        return False
    device = ev.device()
    return device is not None and device.systemId() in TOUCH_SCREEN_IDS


def slide_pixels(ev) -> tuple[float, float]:
    """The slide as a pointer drag in pixels: the model follows the
    fingers, the way a mouse drag grabs it (``OrbitCamera.orbit``).

    The OS hands the deltas in the direction the *content* should move
    when natural scrolling is on (``inverted()``), which is the fingers'
    direction; without natural scrolling they are a wheel's and point the
    other way, like a wheel pushed away scrolls up."""
    d = ev.pixelDelta()
    if d.isNull():
        a = ev.angleDelta()                     # eighths of a degree
        dx, dy = a.x() / 8.0, a.y() / 8.0
    else:
        dx, dy = float(d.x()), float(d.y())
    if not ev.inverted():
        dx, dy = -dx, -dy
    return dx, dy


def slide_mode(ev, default: str) -> str:
    """Shift pans (as with the middle button), Cmd/Ctrl zooms, else the
    preference."""
    mods = ev.modifiers()
    if mods & Qt.ShiftModifier:
        return "pan"
    if mods & Qt.ControlModifier:
        return "zoom"
    return default if default in SLIDE_MODES else DEFAULT_SLIDE


def pinch_steps(value: float) -> float | None:
    """A pinch step (``+0.05`` = 5 % bigger) as the matching fraction of a
    wheel notch, so a pinch and the wheel share one zoom. ``None`` for a
    step that would collapse the scale (never sent in practice)."""
    if value <= -1.0 or not math.isfinite(value):
        return None
    return math.log1p(value) / _NOTCH


# ---- the gesture in progress -----------------------------------------------

class Gesture:
    __slots__ = ("lock", "pinch_sum", "pinch_steps", "slide_sum",
                 "slide_dx", "slide_dy", "last_t", "pivot", "depth")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.lock = None            # None | "slide" | "pinch"
        self.pinch_sum = 0.0
        self.pinch_steps = 0.0
        self.slide_sum = 0.0
        self.slide_dx = 0.0
        self.slide_dy = 0.0
        self.last_t = 0.0
        self.pivot = None
        self.depth = None


def gesture(view) -> Gesture:
    g = getattr(view, "_trackpad_gesture", None)
    if g is None:
        g = view._trackpad_gesture = Gesture()
    return g


def _touch(g: Gesture, now: float, restart: bool = False) -> None:
    if restart or now - g.last_t > IDLE_RESET_S:
        g.reset()
    g.last_t = now


def _depth_of(view, point):
    if point is None:
        return None
    cam = view.camera
    return QVector3D.dotProduct(point - cam.eye(), cam.forward())


# ---- handlers --------------------------------------------------------------

def slide(view, ev) -> bool:
    """Handle a wheel event that is a finger slide. Returns True when the
    event is taken (orbited, panned, or dropped); False when the caller
    should zoom with it as with a wheel."""
    if not is_slide(ev):
        return False
    g = gesture(view)
    now = time.monotonic()
    phase = ev.phase()
    _touch(g, now, restart=phase == Qt.ScrollBegin)
    if phase == Qt.ScrollBegin:
        ev.accept()                 # no delta yet; the pivot waits for one
        return True
    if g.lock == "pinch":
        ev.accept()                 # the fingers are pinching, not sliding
        return True
    if is_touch_screen(ev):
        default = _pref(view, "_touch_slide", load_touch_slide)
    else:
        default = _pref(view, "_trackpad_slide", load_slide_mode)
    mode = slide_mode(ev, default)
    if mode == "zoom":
        return False                # the wheel's zoom, momentum included
    if (phase == Qt.ScrollMomentum
            and not _pref(view, "_trackpad_inertia", load_inertia)):
        ev.accept()
        return True
    dx, dy = slide_pixels(ev)
    if g.lock is None:
        g.slide_dx += dx
        g.slide_dy += dy
        g.slide_sum += math.hypot(dx, dy)
        if g.slide_sum < SLIDE_LOCK_PX:
            ev.accept()             # too early to tell a slide from a pinch
            return True
        g.lock = "slide"
        dx, dy = g.slide_dx, g.slide_dy
    if g.pivot is None:
        pos = ev.position()
        g.pivot = view._orbit_pivot_at(pos.x(), pos.y())
        g.depth = _depth_of(view, g.pivot)
    cam = view.camera
    if mode == "pan":
        cam.pan(dx, dy, view.height(), depth=g.depth)
    else:
        if _pref(view, "_invert_orbit_y", lambda: False):
            dy = -dy
        if g.pivot is not None:
            cam.orbit_about(g.pivot, dx, dy, view.height())
        else:
            cam.orbit(dx, dy, view.height())
    ev.accept()
    return True


def native_gesture(view, ev) -> bool:
    """Handle a ``QNativeGestureEvent``. Returns True when it was taken."""
    kind = ev.gestureType()
    g = gesture(view)
    now = time.monotonic()
    if kind == Qt.BeginNativeGesture:
        _touch(g, now, restart=True)
        ev.accept()
        return True
    if kind == Qt.EndNativeGesture:
        g.reset()
        ev.accept()
        return True
    if kind == Qt.ZoomNativeGesture:
        _touch(g, now)
        ev.accept()
        if g.lock == "slide":
            return True             # the fingers are sliding, not pinching
        steps = pinch_steps(ev.value())
        if steps is None:
            return True
        if g.lock is None:
            g.pinch_sum += abs(math.log1p(ev.value()))
            g.pinch_steps += steps
            if g.pinch_sum < math.log1p(PINCH_LOCK_SHARE):
                return True
            g.lock = "pinch"
            steps = g.pinch_steps
        view._input_t = now
        view._input_serial = getattr(view, "_input_serial", 0) + 1
        view._zoom_at(steps, ev.position())
        view.update()
        return True
    if kind == Qt.SmartZoomNativeGesture:
        signal = getattr(view, "smartZoomRequested", None)
        if signal is None:
            source = getattr(view, "source_viewport", None)
            signal = getattr(source, "smartZoomRequested", None)
        if signal is not None:
            signal.emit()
        ev.accept()
        return True
    if kind in (Qt.RotateNativeGesture, Qt.PanNativeGesture,
                Qt.SwipeNativeGesture):
        ev.accept()                 # the camera has no roll; nothing to do
        return True
    return False
