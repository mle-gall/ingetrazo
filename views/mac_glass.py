"""Liquid Glass chrome on macOS 26+ (Tahoe and later).

Qt Widgets draw everything into one NSView per window, so AppKit's glass
cannot be given to a QToolBar or a dock directly. Instead, AppKit glass
views are placed *behind* Qt's view (as siblings in the window's frame
view), the window is made non-opaque, and the Qt chrome above them paints
nothing, or a faint tint, where glass should show. Each glass panel follows
the geometry of the Qt widget it backs.

    window ── NSThemeFrame
                ├── NSVisualEffectView  (the window's base: under-window blur)
                ├── NSGlassEffectView   (one per backed widget: tray, toolbars)
                └── QNSView             (Qt, transparent where glass shows)

Pure ctypes on the Objective-C runtime: no PyObjC dependency, in keeping
with requirements.txt. Anywhere else, or on macOS before 26, or when the
user turns it off (Preferences ▸ General ▸ «Translucent window chrome»),
every call here is a no-op and the opaque Fusion chrome is unchanged.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import platform
import sys

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer

_KEY = "mac_glass"       # a General setting, on by default where supported


def supported() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return False
    if major < 26:
        return False
    # Only on Qt's native macOS platform: under ``offscreen`` (the test
    # suite) or ``minimal`` there is no NSView behind a widget.
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None \
            or QGuiApplication.platformName() != "cocoa":
        return False
    return _objc() is not None


_enabled: bool | None = None


def enabled() -> bool:
    """Glass on for this run: supported and not turned off in Preferences.
    Read once — a change applies at the next start, so every window of a
    run agrees."""
    global _enabled
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        return False                    # too early to know; not cached
    if _enabled is None:
        _enabled = False
        if supported():
            from core import general_settings
            value = general_settings.value(_KEY, True)
            _enabled = str(value).lower() not in ("false", "0", "no")
    return _enabled


def set_enabled(on: bool) -> None:
    from core import general_settings
    general_settings.set_value(_KEY, bool(on))


# ---- a minimal Objective-C bridge -------------------------------------------

class _CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("w", ctypes.c_double), ("h", ctypes.c_double)]


_lib = None


def _objc():
    global _lib
    if _lib is None:
        try:
            lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/AppKit.framework/AppKit")
        except OSError:
            _lib = False
            return None
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        _lib = lib
    return _lib or None


def _cls(name: str):
    return _objc().objc_getClass(name.encode())


def _send(obj, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend with an explicit signature (arm64 needs the real one)."""
    lib = _objc()
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p,
                          *argtypes)(("objc_msgSend", lib))
    return fn(obj, lib.sel_registerName(selector.encode()), *args)


def _responds(obj, selector: str) -> bool:
    return bool(_send(obj, "respondsToSelector:",
                      _objc().sel_registerName(selector.encode()),
                      restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)))


_NSWindowBelow = -1
_NSTitleHidden = 1
_GLASS_REGULAR, _GLASS_CLEAR = 0, 1      # NSGlassEffectView.Style
#: Qt::ExpandedClientAreaHint (Qt 6.9+; PySide 6.11 only names its
#: deprecated alias MaximizeUsingFullscreenGeometryHint).
_EXPANDED_CLIENT_AREA = 0x00400000
_NSViewWidthSizable, _NSViewHeightSizable = 2, 16
# NSVisualEffectView
_MATERIAL_WINDOW_BACKGROUND = 12
_BLENDING_BEHIND_WINDOW = 0
_STATE_FOLLOWS_WINDOW = 0


def _set_frame(view, rect: QRect, host_h: float) -> None:
    # AppKit's frame view is not flipped: y grows upwards.
    r = _CGRect(rect.x(), host_h - rect.y() - rect.height(),
                rect.width(), rect.height())
    _send(view, "setFrame:", r, restype=None, argtypes=(_CGRect,))


def _bounds(view) -> _CGRect:
    return _send(view, "bounds", restype=_CGRect)


# ---- the title-bar row --------------------------------------------------------
# The first toolbar row shares its line with the traffic lights, as in a
# macOS 26 window with a unified toolbar. AppKit's title-bar views, though,
# sit over that line and kept every press in it — for the title bar, then
# for the window server's window drag — so no tool there could be clicked,
# whatever of their hit-testing was patched (Maxence, 2026-11-07). The
# title-bar container is hidden instead and the three window buttons are
# moved out of it onto the window's frame view, over Qt's: the line is
# then Qt's alone, and only the buttons themselves are AppKit's.
# (Tested with real clicks: every press on a top tool landed, the first
# one on an inactive window included.)

_NSWindowAbove = 1
_NSViewMinYMargin = 8
#: Where the buttons' row starts, and the room they take, in points.
LIGHTS_LEFT = 14
LIGHTS_WIDTH = 76


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


# The buttons show their glyphs (×, −, +) while the mouse is over the
# group: each asks its superview ``_mouseInGroup:``, which on the frame view
# answers from the hidden title bar's tracking — never yes. For a glass
# window it answers from a tracking area of ours over the three buttons.
_hover: dict = {}                   # NSWindow pointer -> mouse over the room
_hover_hook: list = []


def _install_hover_hook() -> None:
    if _hover_hook:
        return
    lib = _objc()
    lib.class_getMethodImplementation.restype = ctypes.c_void_p
    lib.class_getMethodImplementation.argtypes = [ctypes.c_void_p,
                                                  ctypes.c_void_p]
    lib.class_replaceMethod.restype = ctypes.c_void_p
    lib.class_replaceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_char_p]
    cls = _cls("NSThemeFrame")
    sel = lib.sel_registerName(b"_mouseInGroup:")
    if not cls:
        return
    imp = lib.class_getMethodImplementation(cls, sel)
    if not imp:
        return
    proto = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p)
    original = proto(imp)

    def in_group(this, sel_, button):
        try:
            win = _send(this, "window")
            if win in _hover:
                return _hover[win]
        except Exception:  # noqa: BLE001 — never break the window
            pass
        return original(this, sel_, button)

    ours = proto(in_group)
    _hover_hook[:] = [original, ours]
    lib.class_replaceMethod(cls, sel, ctypes.cast(ours, ctypes.c_void_p),
                            b"B@:@")


_tracker: list = []                 # [owner instance, its callbacks]


def _hover_owner():
    """An NSObject subclass made at run time whose mouseEntered: and
    mouseExited: set the window's hover flag and redraw its buttons."""
    if _tracker:
        return _tracker[0]
    lib = _objc()
    lib.objc_allocateClassPair.restype = ctypes.c_void_p
    lib.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                           ctypes.c_size_t]
    lib.objc_registerClassPair.argtypes = [ctypes.c_void_p]
    lib.class_addMethod.restype = ctypes.c_bool
    lib.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_char_p]
    proto = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p)

    def hover(on):
        def handler(_self, _sel, event):
            try:
                win = _send(event, "window")
                if win in _hover and _hover[win] != on:
                    _hover[win] = on
                    for kind in range(3):
                        b = _send(win, "standardWindowButton:", kind,
                                  argtypes=(ctypes.c_long,))
                        if not b:
                            continue
                        # macOS 26 fades the glyphs in by a reveal amount
                        # it sets from _mouseInGroup: here.
                        if _responds(b, "mouseEnteredOrExited"):
                            _send(b, "mouseEnteredOrExited", restype=None)
                        if _responds(b, "setRevealAmount:"):
                            _send(b, "setRevealAmount:", 1.0 if on else 0.0,
                                  restype=None, argtypes=(ctypes.c_double,))
                        _send(b, "setNeedsDisplay:", True, restype=None,
                              argtypes=(ctypes.c_bool,))
            except Exception:  # noqa: BLE001
                pass
        return proto(handler)

    cls = _cls("IngeTrazoLightsHover")
    entered, exited = hover(True), hover(False)
    if not cls:
        cls = lib.objc_allocateClassPair(_cls("NSObject"),
                                         b"IngeTrazoLightsHover", 0)
        for name, fn in ((b"mouseEntered:", entered),
                         (b"mouseExited:", exited)):
            lib.class_addMethod(cls, lib.sel_registerName(name),
                                ctypes.cast(fn, ctypes.c_void_p), b"v@:@")
        lib.objc_registerClassPair(cls)
    owner = _send(_send(cls, "alloc"), "init")
    _tracker[:] = [owner, entered, exited]
    return owner


def _class_name(obj) -> bytes:
    lib = _objc()
    lib.object_getClassName.restype = ctypes.c_char_p
    lib.object_getClassName.argtypes = [ctypes.c_void_p]
    return lib.object_getClassName(obj) or b""


def _subviews(view) -> list:
    arr = _send(view, "subviews")
    n = _send(arr, "count", restype=ctypes.c_ulong) if arr else 0
    return [_send(arr, "objectAtIndex:", i, argtypes=(ctypes.c_ulong,))
            for i in range(n)]


# ---- the per-window controller ----------------------------------------------

#: Corner radii, in points: the sidebar is a floating glass slab.
SIDEBAR_RADIUS = 16.0
#: A row of top bars: a rounded rectangle concentric with the 7 px
#: rounded checked state of its buttons, a few points inside it.
ROW_RADIUS = 10.0
#: The box of the side tool palette: a rounded rectangle, not a pill.
COLUMN_RADIUS = 12.0
#: Room left at both ends of a top-row box.
ROW_INSET = 3
#: Gap between a glass slab and the window edge / its neighbours.
INSET = 4
#: The traffic lights' room among the toolbars.
LIGHTS_NAME = "mac_titlebar_lights"

SIDEBAR, TOOLBAR = "sidebar", "toolbar"


class GlassWindow(QObject):
    """Owns the AppKit glass views behind one Qt top-level window.

    ``regions`` is a callable returning ``[(QRect, radius, kind), ...]`` in
    the window's coordinates: what should sit on Liquid Glass right now. It
    is asked again whenever the window or one of the watched widgets moves,
    resizes, shows or hides; glass views are pooled, never torn down.

    AppKit places them in the window's frame view, under Qt's view. That
    is not a place AppKit expects views of ours, and it lays the window
    title out wrongly once there are any — so the title is hidden, as in
    every macOS 26 window with a unified toolbar; the document tabs name
    the document."""

    def __init__(self, window, regions) -> None:
        super().__init__(window)
        self._window = window
        self._regions = regions
        self._pool: list[int] = []
        self._tint = None
        self._ns_view = int(window.winId())
        self._ns_window = _send(self._ns_view, "window")
        self._frame = _send(self._ns_view, "superview")
        nw = self._ns_window
        _send(nw, "setOpaque:", False, restype=None, argtypes=(ctypes.c_bool,))
        _send(nw, "setBackgroundColor:", _send(_cls("NSColor"), "clearColor"),
              restype=None, argtypes=(ctypes.c_void_p,))
        _send(nw, "setTitlebarAppearsTransparent:", True,
              restype=None, argtypes=(ctypes.c_bool,))
        _send(nw, "setTitleVisibility:", _NSTitleHidden,
              restype=None, argtypes=(ctypes.c_long,))
        self._base = self._make_base()
        self._wash = self._make_wash()
        self.retint()
        # The traffic lights: [(button, its own superview)], taken out of
        # the title bar in place_lights().
        self._lights: list = []
        self._lights_out = False
        self._sync = QTimer(self, singleShot=True, interval=0,
                            timeout=self.sync)
        self.watch(window)

    def watch(self, widget) -> None:
        widget.installEventFilter(self)
        self._sync.start()

    # -- the traffic lights (see "the title-bar row") ------------------------
    def _title_containers(self):
        return [v for v in _subviews(self._frame)
                if _class_name(v) == b"NSTitlebarContainerView"]

    def place_lights(self, centre_y: float | None) -> None:
        """Put the window buttons on the first toolbar row, centred on
        ``centre_y`` (window coordinates, from the top), and hide the title
        bar; ``None`` gives them back to the title bar (full screen, where
        AppKit's title bar slides in with them)."""
        nw = self._ns_window
        if not self._lights:
            for kind in range(3):       # close, miniaturize, zoom
                b = _send(nw, "standardWindowButton:", kind,
                          argtypes=(ctypes.c_long,))
                if b:
                    _send(b, "retain")  # it changes superview, kept alive
                    self._lights.append((b, _send(b, "superview")))
        if not self._lights:
            return
        _install_hover_hook()
        _hover.setdefault(nw, False)
        if centre_y is None:
            if self._lights_out:
                for b, home in self._lights:
                    _send(b, "removeFromSuperview", restype=None)
                    _send(home, "addSubview:", b, restype=None,
                          argtypes=(ctypes.c_void_p,))
                for v in self._title_containers():
                    _send(v, "setHidden:", False, restype=None,
                          argtypes=(ctypes.c_bool,))
                self._lights_out = False
            return
        host_h = _bounds(self._frame).h
        x = float(LIGHTS_LEFT)
        for b, _home in self._lights:
            if _send(b, "superview") != self._frame:
                _send(b, "removeFromSuperview", restype=None)
                _send(self._frame, "addSubview:positioned:relativeTo:", b,
                      _NSWindowAbove, self._ns_view, restype=None,
                      argtypes=(ctypes.c_void_p, ctypes.c_long,
                                ctypes.c_void_p))
                # Stay at the same distance from the top when it resizes.
                _send(b, "setAutoresizingMask:", _NSViewMinYMargin,
                      restype=None, argtypes=(ctypes.c_ulong,))
            size = _send(b, "frame", restype=_CGRect)
            _send(b, "setFrameOrigin:",
                  _Point(round(x), round(host_h - centre_y - size.h / 2)),
                  restype=None, argtypes=(_Point,))
            x += size.w + 6
        for v in self._title_containers():
            _send(v, "setHidden:", True, restype=None,
                  argtypes=(ctypes.c_bool,))
        self._lights_out = True
        self._track_lights()

    def _track_lights(self) -> None:
        """The tracking area over the three buttons, where they are now."""
        rects = [_send(b, "frame", restype=_CGRect) for b, _h in self._lights]
        x0 = min(r.x for r in rects) - 2
        y0 = min(r.y for r in rects) - 2
        x1 = max(r.x + r.w for r in rects) + 2
        y1 = max(r.y + r.h for r in rects) + 2
        area = getattr(self, "_lights_area", None)
        if area:
            _send(self._frame, "removeTrackingArea:", area, restype=None,
                  argtypes=(ctypes.c_void_p,))
            _send(area, "release", restype=None)
        # NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways
        area = _send(_send(_cls("NSTrackingArea"), "alloc"),
                     "initWithRect:options:owner:userInfo:",
                     _CGRect(x0, y0, x1 - x0, y1 - y0), 0x01 | 0x80,
                     _hover_owner(), None,
                     argtypes=(_CGRect, ctypes.c_ulong, ctypes.c_void_p,
                               ctypes.c_void_p))
        _send(self._frame, "addTrackingArea:", area, restype=None,
              argtypes=(ctypes.c_void_p,))
        self._lights_area = area

    def _make_base(self):
        view = _send(_send(_cls("NSVisualEffectView"), "alloc"),
                     "initWithFrame:", _bounds(self._frame),
                     argtypes=(_CGRect,))
        for sel, val in (("setMaterial:", _MATERIAL_WINDOW_BACKGROUND),
                         ("setBlendingMode:", _BLENDING_BEHIND_WINDOW),
                         ("setState:", _STATE_FOLLOWS_WINDOW)):
            _send(view, sel, val, restype=None, argtypes=(ctypes.c_long,))
        _send(view, "setAutoresizingMask:",
              _NSViewWidthSizable | _NSViewHeightSizable,
              restype=None, argtypes=(ctypes.c_ulong,))
        self._add_below_qt(view)
        return view

    # Over the base, under the glass: a translucent wash of IngeTrazo's
    # blue, so the whole chrome — and the glass, which takes the colour of
    # what is behind it — wears the brand tint, as the opaque dark theme's
    # blue-grey did.
    def _make_wash(self):
        view = _send(_send(_cls("NSView"), "alloc"), "initWithFrame:",
                     _bounds(self._frame), argtypes=(_CGRect,))
        _send(view, "setWantsLayer:", True, restype=None,
              argtypes=(ctypes.c_bool,))
        _send(view, "setAutoresizingMask:",
              _NSViewWidthSizable | _NSViewHeightSizable,
              restype=None, argtypes=(ctypes.c_ulong,))
        self._add_below_qt(view)
        return view

    def retint(self) -> None:
        """The wash for the theme in force (views.theme calls it through
        apply_palette)."""
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication
        from views.theme import brand_tint
        dark = QApplication.palette().color(QPalette.Window).lightness() < 128
        color = self._ns_color(brand_tint(dark))
        cg = _send(color, "CGColor")
        _send(_send(self._wash, "layer"), "setBackgroundColor:", cg,
              restype=None, argtypes=(ctypes.c_void_p,))
        if self._pool:
            self.sync()                 # the glass follows the theme too

    def _add_below_qt(self, view) -> None:
        _send(self._frame, "addSubview:positioned:relativeTo:",
              view, _NSWindowBelow, self._ns_view, restype=None,
              argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))
        _send(view, "release", restype=None)      # the frame view owns it

    def _glass_view(self, index: int):
        while len(self._pool) <= index:
            cls = _cls("NSGlassEffectView") or _cls("NSVisualEffectView")
            view = _send(_send(cls, "alloc"), "initWithFrame:",
                         _CGRect(0, 0, 10, 10), argtypes=(_CGRect,))
            self._add_below_qt(view)
            self._pool.append(view)
        return self._pool[index]

    def set_toolbar_tint(self, color) -> None:
        """Tint the toolbar capsules (a QColor), or None for plain glass —
        the customize mode lights them up in the accent."""
        self._tint = color
        self.sync()

    def _ns_color(self, color):
        if color is None:
            return None
        return _send(_cls("NSColor"),
                     "colorWithSRGBRed:green:blue:alpha:",
                     color.redF(), color.greenF(), color.blueF(),
                     color.alphaF(),
                     argtypes=(ctypes.c_double,) * 4)

    def sync(self) -> None:
        try:
            regions = [(r, rad, kind) for r, rad, kind in self._regions()
                       if r.isValid() and not r.isEmpty()]
        except RuntimeError:            # a widget's C++ side already gone
            return
        host_h = _bounds(self._frame).h
        # Qt's view may not start at the frame view's top-left.
        origin = _send(self._ns_view, "frame", restype=_CGRect)
        top = host_h - (origin.y + origin.h)
        tint = self._ns_color(self._tint)
        # Dark theme: the clear glass, tinted with the chrome's navy — the
        # regular glass frosts itself light and the panels stood out pale
        # over the near-black chrome (Maxence, 07-11). Light: regular.
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication
        from views.theme import glass_tint
        dark = QApplication.palette().color(QPalette.Window).lightness() < 128
        glass_style = _GLASS_CLEAR if dark else _GLASS_REGULAR
        base_tint = self._ns_color(glass_tint(dark))
        for i, (rect, radius, kind) in enumerate(regions):
            view = self._glass_view(i)
            if _responds(view, "setCornerRadius:"):
                _send(view, "setCornerRadius:", float(radius),
                      restype=None, argtypes=(ctypes.c_double,))
            if _responds(view, "setStyle:"):
                _send(view, "setStyle:", glass_style,
                      restype=None, argtypes=(ctypes.c_long,))
            if _responds(view, "setTintColor:"):
                _send(view, "setTintColor:",
                      tint if kind == TOOLBAR and tint is not None
                      else base_tint,
                      restype=None, argtypes=(ctypes.c_void_p,))
            _set_frame(view, rect.translated(int(origin.x), int(top)), host_h)
            _send(view, "setHidden:", False,
                  restype=None, argtypes=(ctypes.c_bool,))
        for view in self._pool[len(regions):]:
            _send(view, "setHidden:", True,
                  restype=None, argtypes=(ctypes.c_bool,))

    def zoom(self) -> None:
        """What a double-click on a Mac title bar does (System Settings ▸
        Desktop & Dock picks zoom or minimize; zoom is the default)."""
        _send(self._ns_window, "performZoom:", None, restype=None,
              argtypes=(ctypes.c_void_p,))

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        kind = event.type()
        if kind in (QEvent.Resize, QEvent.Move, QEvent.Show, QEvent.Hide,
                    QEvent.LayoutRequest, QEvent.ChildAdded):
            self._sync.start()
        return False


def _place(window, w) -> QRect:
    return QRect(w.mapTo(window, w.rect().topLeft()), w.size())


def _view_floor(window):
    """The bottom edge of the view, in window coordinates: the side boxes
    and the sidebar slab end exactly there (None without a central area)."""
    from PySide6.QtWidgets import QMainWindow
    area = getattr(window, "_doc_area", None) or QMainWindow.centralWidget(window)
    if area is None or not area.isVisible():
        return None
    bottom = area.mapTo(window, area.rect().bottomLeft()).y()
    lay = area.layout()
    return bottom - (lay.contentsMargins().bottom() if lay is not None else 0)


def _on_floor(r: QRect, floor) -> QRect:
    # Only a panel that reaches down to the view's level is pinned to it.
    if floor is not None and abs(r.bottom() - floor) <= 3 * INSET:
        r.setBottom(floor)
    return r


def _column_box(r: QRect, floor=None):
    # One gutter everywhere: INSET from the window edge and from the view,
    # whose bottom edge the box shares (as the sidebar slab does).
    r = _on_floor(r.adjusted(INSET, INSET, -INSET, -INSET), floor)
    return (r, min(COLUMN_RADIUS, r.width() / 2), TOOLBAR)


def _row_box(r: QRect):
    r = r.adjusted(ROW_INSET, 0, -ROW_INSET, 0)
    return (r, min(ROW_RADIUS, r.height() / 2), TOOLBAR)


def _set_divider(tb, on: bool) -> None:
    """Mark a bar that follows another in its box: _Chrome paints a
    hairline over its leading edge (its top edge in a side column)."""
    if bool(tb.property("mac_glass_divider")) != on:
        tb.setProperty("mac_glass_divider", on)
        tb.update()


def main_window_regions(window):
    """The glass of a QMainWindow: a slab behind each dock area that has a
    visible dock (tabbed docks and their tab bar together) and a capsule
    behind each docked toolbar, as tall as its buttons and centred in its
    row (the title-bar row is taller than a toolbar)."""
    from PySide6.QtWidgets import QDockWidget, QTabBar, QToolBar

    def regions():
        out = []
        areas: dict = {}
        for dock in window.findChildren(QDockWidget):
            if dock.isVisible() and not dock.isFloating() \
                    and dock.parentWidget() is window:
                area = window.dockWidgetArea(dock)
                areas[area] = areas.get(area, QRect()).united(
                    _place(window, dock))
        # The tab bars QMainWindow puts on tabbed docks belong to them.
        for bar in window.findChildren(QTabBar):
            if bar.parentWidget() is window and bar.isVisible():
                r = _place(window, bar)
                for area, box in areas.items():
                    if abs(r.left() - box.left()) < 8 \
                            or abs(r.right() - box.right()) < 8:
                        areas[area] = box.united(r)
        floor = _view_floor(window)
        for box in areas.values():
            box = box.adjusted(INSET, INSET, -INSET, -INSET)
            out.append((_on_floor(box, floor), SIDEBAR_RADIUS, SIDEBAR))
        column: dict = {}
        rows: dict = {}
        for tb in window.findChildren(QToolBar):
            if not tb.isVisible() or tb.isFloating() \
                    or tb.parentWidget() is not window \
                    or tb.objectName() == LIGHTS_NAME:
                continue
            r = _place(window, tb)
            if tb.orientation() == Qt.Horizontal:
                rows.setdefault((window.toolBarArea(tb), r.y()), []).append(
                    (r, tb))
            else:
                column.setdefault((window.toolBarArea(tb), r.x()), []).append(
                    (r, tb))
        # A row of top bars is one rounded rectangle, the bars in it set
        # apart by hairlines — not a run of capsules side by side, and with
        # corners that echo the rounded checked state of its buttons
        # (Maxence, 2026-11-07). As tall as the buttons, centred in the row.
        for bars in rows.values():
            bars.sort(key=lambda item: item[0].x())
            box = None
            for r, tb in bars:
                h = min(r.height(), tb.sizeHint().height())
                r = QRect(r.x(), r.y() + (r.height() - h) // 2,
                          r.width(), h).adjusted(0, 2, 0, -2)
                joined = box is not None and r.x() - box.right() <= 12
                _set_divider(tb, joined)
                if joined:
                    box = box.united(r)
                    continue
                if box is not None:
                    out.append(_row_box(box))
                box = r
            if box is not None:
                out.append(_row_box(box))
        # A column of side bars is one box, the bars in it set apart by
        # hairlines (the tool palette of a drawing app), not a stack of
        # pills.
        for bars in column.values():
            bars.sort(key=lambda item: item[0].y())
            box = None
            for r, tb in bars:
                joined = box is not None and r.y() - box.bottom() <= 12
                _set_divider(tb, joined)
                if joined:
                    box = box.united(r)
                    continue
                if box is not None:
                    out.append(_column_box(box, floor))
                box = r
            if box is not None:
                out.append(_column_box(box, floor))
        return out
    return regions


# ---- the title-bar row --------------------------------------------------------

class _Chrome(QObject):
    """The behaviour of a window chrome that has replaced the title bar:
    its empty parts drag the window and a double-click zooms it, and the
    toolbars stay put unless the user is customizing them."""

    def __init__(self, window, glass: GlassWindow) -> None:
        super().__init__(window)
        self._window = window
        self._glass = glass
        self.editing = False
        self._bar = None
        self._lights = None
        window.installEventFilter(self)

    # -- toolbars ------------------------------------------------------------
    def toolbars(self):
        from PySide6.QtWidgets import QToolBar
        return [tb for tb in self._window.findChildren(QToolBar)
                if tb.parentWidget() is self._window
                and tb.objectName() != LIGHTS_NAME]

    def adopt(self, tb) -> None:
        """A toolbar of the window — at start-up, or an extension's later."""
        if tb.property("mac_glass_adopted"):
            return
        tb.setProperty("mac_glass_adopted", True)
        tb.installEventFilter(self)
        self._glass.watch(tb)
        self._lock(tb)

    def _lock(self, tb) -> None:
        # A floating toolbar keeps moving: it is a small window of its own.
        if not tb.isFloating():
            tb.setMovable(self.editing)

    def lock_all(self) -> None:
        for tb in self.toolbars():
            self.adopt(tb)
            self._lock(tb)

    def seat_lights(self) -> None:
        """The traffic lights' room: a fixed, empty toolbar kept first in
        the first top row, and the window buttons centred in it."""
        from PySide6.QtWidgets import QToolBar, QWidget
        w = self._window
        lights = self._lights
        if lights is None:
            lights = self._lights = QToolBar(w)
            lights.setObjectName(LIGHTS_NAME)
            lights.setWindowTitle("")
            lights.setMovable(False)
            lights.setFloatable(False)
            lights.toggleViewAction().setVisible(False)
            lights.setContextMenuPolicy(Qt.PreventContextMenu)
            room = QWidget(lights)
            room.setFixedWidth(LIGHTS_WIDTH)
            room.setAttribute(Qt.WA_TransparentForMouseEvents)
            lights.addWidget(room)
            lights.installEventFilter(self)
        top = [tb for tb in self.toolbars()
               if not tb.isFloating() and tb.isVisibleTo(w)
               and w.toolBarArea(tb) == Qt.TopToolBarArea]
        if top:
            first = min(top, key=lambda tb: (tb.y(), tb.x()))
            here = (w.toolBarArea(lights) == Qt.TopToolBarArea
                    and (lights.y(), lights.x()) <= (first.y(), first.x()))
            if not here:
                w.removeToolBar(lights)
                w.insertToolBar(first, lights)
        elif w.toolBarArea(lights) != Qt.TopToolBarArea:
            w.addToolBar(Qt.TopToolBarArea, lights)
        self.fit_lights()

    def fit_lights(self) -> None:
        """The window buttons over their room — or, in full screen, back in
        AppKit's title bar and no room kept."""
        lights = self._lights
        if lights is None:
            return
        full = bool(self._window.windowState() & Qt.WindowFullScreen)
        lights.setVisible(not full)
        if full:
            self._glass.place_lights(None)
            return
        # Laid out yet? Its row's centre; else the row's usual height.
        y = lights.y() + lights.height() / 2 if lights.height() > 1 else 20
        self._glass.place_lights(y)

    # -- customizing -----------------------------------------------------------
    def set_editing(self, on: bool) -> None:
        if on == self.editing:
            return
        self.editing = on
        for tb in self.toolbars():
            self._lock(tb)
        from views.theme import accent_color, style
        style(self._window, _window_sheet(self._window, on))
        tint = None
        if on:
            tint = accent_color()
            tint.setAlphaF(0.35)
        self._glass.set_toolbar_tint(tint)
        if on:
            if self._bar is None:
                self._bar = _CustomizeBar(self._window, self)
            self._bar.popup()
        elif self._bar is not None:
            self._bar.hide()
            # Toolbars moved meanwhile: each to its own length again, and
            # the title-bar room first in its row.
            pack = getattr(self._window, "_pack_toolbars", None)
            if callable(pack):
                pack()
            self.seat_lights()

    # -- events ----------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        from PySide6.QtWidgets import QToolBar
        kind = event.type()
        if obj is self._window:
            if kind == QEvent.ChildAdded and isinstance(event.child(),
                                                        QToolBar):
                QTimer.singleShot(0, self, self.lock_all)
            elif kind in (QEvent.Show, QEvent.Resize, QEvent.WindowStateChange,
                          QEvent.WindowActivate, QEvent.WindowDeactivate):
                # AppKit lays its title bar out again on these.
                QTimer.singleShot(0, self, self.fit_lights)
            return False
        if obj is self._lights:
            if kind in (QEvent.Move, QEvent.Resize, QEvent.Show):
                QTimer.singleShot(0, self, self.fit_lights)

        if kind == QEvent.Paint:
            if obj.property("mac_glass_divider"):
                _paint_divider(obj)
            return False
        if kind == QEvent.MouseButtonPress \
                and event.button() == Qt.LeftButton and not self.editing:
            # On the toolbar itself: between its buttons, not on one.
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return True
        elif kind == QEvent.MouseButtonDblClick \
                and event.button() == Qt.LeftButton and not self.editing:
            self._glass.zoom()
            return True
        return False


def _paint_divider(tb) -> None:
    """The hairline between two bars of a box, inset from its edges.
    Painted before the bar's own (transparent) background and buttons."""
    from PySide6.QtGui import QColor, QPainter, QPalette
    from PySide6.QtWidgets import QApplication
    dark = QApplication.palette().color(QPalette.Window).lightness() < 128
    p = QPainter(tb)
    p.setPen(QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 40))
    inset = 8
    if tb.orientation() == Qt.Vertical:
        p.drawLine(inset, 0, tb.width() - inset - 1, 0)
    else:
        # The title-bar row is taller than the box, which is centred in it.
        inset += max(0, (tb.height() - tb.sizeHint().height()) // 2)
        p.drawLine(0, inset, 0, tb.height() - inset - 1)
    p.end()


class _CustomizeBar(QObject):
    """The floating pill of the customize mode, over the bottom of the
    view: what to do, Restore Defaults and Done (Return or Esc)."""

    def __init__(self, window, chrome: _Chrome) -> None:
        super().__init__(window)
        from PySide6.QtGui import QKeySequence, QShortcut
        from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel,
                                       QPushButton)
        from core.i18n import tr
        self._window = window
        frame = self.frame = QFrame(window)
        frame.setObjectName("mac_customize_bar")
        row = QHBoxLayout(frame)
        row.setContentsMargins(18, 10, 10, 10)
        row.setSpacing(10)
        label = QLabel(tr("Drag toolbars by their grips to rearrange them. "
                          "Right-click one to show or hide toolbars."),
                       frame)
        row.addWidget(label)
        row.addSpacing(8)
        reset = QPushButton(tr("Restore Defaults"), frame)
        reset.setAutoDefault(False)
        restore = getattr(window, "restore_default_toolbars", None)
        if callable(restore):
            reset.clicked.connect(restore)
        else:
            reset.hide()
        row.addWidget(reset)
        done = QPushButton(tr("Done"), frame)
        done.setDefault(True)
        done.clicked.connect(lambda: chrome.set_editing(False))
        row.addWidget(done)
        from views.theme import style
        style(frame,
              "#mac_customize_bar {{ background: palette(base);"
              " border: 1px solid rgba({ink_rgb}, 40); border-radius: 22px; }}"
              "QLabel {{ background: transparent; }}")
        # Over glass the palette's Base is a veil: this pill floats over the
        # 3D view and needs the opaque application colour.
        from PySide6.QtWidgets import QApplication
        frame.setPalette(QApplication.palette())
        self._keys = []
        for key in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            sc = QShortcut(QKeySequence(key), window)
            sc.setEnabled(False)
            sc.activated.connect(lambda: chrome.set_editing(False))
            self._keys.append(sc)
        window.installEventFilter(self)
        frame.hide()

    def popup(self) -> None:
        self.frame.adjustSize()
        self._place()
        self.frame.show()
        self.frame.raise_()
        for sc in self._keys:
            sc.setEnabled(True)

    def hide(self) -> None:
        self.frame.hide()
        for sc in self._keys:
            sc.setEnabled(False)

    def _place(self) -> None:
        w = self._window
        central = w.centralWidget()
        box = _place(w, central) if central is not None else w.rect()
        f = self.frame
        f.move(box.center().x() - f.width() // 2,
               box.bottom() - f.height() - 24)

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Resize and self.frame.isVisible():
            self._place()
        return False


# ---- menus ---------------------------------------------------------------------

_MATERIAL_MENU = 5
_MATERIAL_TOOLTIP = 17
TOOLTIP_RADIUS = 7.0
_STATE_ACTIVE = 1
MENU_RADIUS = 10.0

#: A Qt menu drawn as a macOS 26 one: no frame of its own (the AppKit
#: material behind it, rounded, is the menu), items inset with a rounded
#: highlight in the system accent, hairline separators.
MENU_SHEET = (
    "QMenu {{ background: transparent; border: none; padding: 5px; }}"
    "QMenu::item {{ padding: 3px 22px 3px 22px; border-radius: 5px;"
    " background: transparent; }}"
    "QMenu::item:selected {{ background: rgb({system_accent_rgb});"
    " color: white; }}"
    "QMenu::item:disabled {{ color: rgba({ink_rgb}, 80); }}"
    "QMenu::separator {{ height: 1px; background: rgba({ink_rgb}, 30);"
    " margin: 5px 10px; }}"
    "QMenu::indicator {{ width: 14px; height: 14px; left: 5px; }}"
    "QMenu::right-arrow {{ right: 6px; }}"
)


class _MenuGlass(QObject):
    """Application-wide: every QMenu (context menus, toolbar drop-downs)
    on the AppKit menu material with rounded corners — the native menu bar
    is AppKit's already — and every dialog with CONTROLS_SHEET."""

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        from PySide6.QtWidgets import QMenu
        kind = event.type()
        if kind == QEvent.Polish and isinstance(obj, QMenu) \
                and not obj.property("mac_glass_menu"):
            obj.setProperty("mac_glass_menu", True)
            if not obj.testAttribute(Qt.WA_WState_Created):
                obj.setAttribute(Qt.WA_TranslucentBackground, True)
                from views.theme import style
                style(obj, MENU_SHEET)
        elif kind == QEvent.Polish and obj.isWidgetType() \
                and obj.isWindow() and _is_dialog(obj) \
                and not obj.styleSheet() and not obj.property("mac_glass_dlg"):
            # A dialog keeps its opaque window but speaks the same control
            # language as the glass windows.
            obj.setProperty("mac_glass_dlg", True)
            from views.theme import style
            style(obj, CONTROLS_SHEET)
            # AppKit forms right-align their labels against the controls.
            from PySide6.QtWidgets import QFormLayout
            for form in obj.findChildren(QFormLayout):
                form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        elif kind == QEvent.Polish and _is_tooltip(obj) \
                and not obj.property("mac_glass_menu"):
            # Tooltips: AppKit's tooltip material, rounded, no Fusion box.
            obj.setProperty("mac_glass_menu", True)
            if not obj.testAttribute(Qt.WA_WState_Created):
                obj.setAttribute(Qt.WA_TranslucentBackground, True)
        elif kind == QEvent.Show \
                and (isinstance(obj, QMenu) or _is_tooltip(obj)) \
                and obj.testAttribute(Qt.WA_TranslucentBackground) \
                and not obj.property("mac_glass_backed"):
            obj.setProperty("mac_glass_backed", True)
            tip = _is_tooltip(obj)
            try:
                _back_popup(obj, _MATERIAL_TOOLTIP if tip else _MATERIAL_MENU,
                            TOOLTIP_RADIUS if tip else MENU_RADIUS)
            except Exception:       # never let a menu fail to open over it
                pass
        return False


def _is_dialog(widget) -> bool:
    from PySide6.QtWidgets import QDialog
    return isinstance(widget, QDialog)


def _is_tooltip(obj) -> bool:
    return obj.isWidgetType() and obj.metaObject().className() == "QTipLabel"


def _back_popup(widget, material: int = 5, radius: float = 10.0) -> None:
    ns_view = int(widget.winId())
    nw = _send(ns_view, "window")
    frame = _send(ns_view, "superview")
    _send(nw, "setOpaque:", False, restype=None, argtypes=(ctypes.c_bool,))
    _send(nw, "setBackgroundColor:", _send(_cls("NSColor"), "clearColor"),
          restype=None, argtypes=(ctypes.c_void_p,))
    view = _send(_send(_cls("NSVisualEffectView"), "alloc"),
                 "initWithFrame:", _bounds(frame), argtypes=(_CGRect,))
    for sel, val in (("setMaterial:", material),
                     ("setBlendingMode:", _BLENDING_BEHIND_WINDOW),
                     ("setState:", _STATE_ACTIVE)):
        _send(view, sel, val, restype=None, argtypes=(ctypes.c_long,))
    _send(view, "setAutoresizingMask:",
          _NSViewWidthSizable | _NSViewHeightSizable,
          restype=None, argtypes=(ctypes.c_ulong,))
    _send(view, "setWantsLayer:", True, restype=None,
          argtypes=(ctypes.c_bool,))
    layer = _send(view, "layer")
    _send(layer, "setCornerRadius:", float(radius), restype=None,
          argtypes=(ctypes.c_double,))
    _send(layer, "setMasksToBounds:", True, restype=None,
          argtypes=(ctypes.c_bool,))
    _send(frame, "addSubview:positioned:relativeTo:", view, _NSWindowBelow,
          ns_view, restype=None,
          argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))
    _send(view, "release", restype=None)
    # The shadow follows the rounded shape, not the window's square.
    _send(nw, "setHasShadow:", True, restype=None, argtypes=(ctypes.c_bool,))
    _send(nw, "invalidateShadow", restype=None)


_menu_glass: _MenuGlass | None = None


def install_menus(app) -> None:
    """Every QMenu of the application in the macOS 26 idiom, and every
    dialog with the glass windows' controls; a no-op where glass is off."""
    global _menu_glass
    if _menu_glass is None and enabled():
        _menu_glass = _MenuGlass(app)
        app.installEventFilter(_menu_glass)


# ---- installing -----------------------------------------------------------------

def prepare(window) -> bool:
    """Call first thing in a glass window's constructor, before anything
    creates its native window: translucent, with the client area under the
    title bar. True when glass is on for it."""
    if not enabled():
        return False
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    window.setWindowFlag(Qt.WindowType(_EXPANDED_CLIENT_AREA), True)
    # The first toolbar row on the title bar's line: see "the title-bar row".
    window.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
    return True


def install(window) -> GlassWindow | None:
    """Put a QMainWindow's chrome on Liquid Glass. None (and nothing
    changed) where glass is off or unsupported, or when :func:`prepare`
    was not called before the window was created."""
    if not enabled() or not window.testAttribute(Qt.WA_TranslucentBackground):
        return None
    glass = GlassWindow(window, main_window_regions(window))
    from PySide6.QtWidgets import QDockWidget
    for w in window.findChildren(QDockWidget):
        glass.watch(w)
    # The view's top and bottom on the gutter the glass panels keep, so
    # the left box, the view and the sidebar slab line up.
    from PySide6.QtWidgets import QMainWindow
    area = getattr(window, "_doc_area", None) or QMainWindow.centralWidget(window)
    if area is not None and area.layout() is not None:
        m = area.layout().contentsMargins()
        area.layout().setContentsMargins(m.left(), INSET, m.right(), INSET)
    status = window.statusBar() if hasattr(window, "statusBar") else None
    if status is not None:
        # Its first pill (the Model/sheet tabs) on the boxes' left edge.
        status.setContentsMargins(1, 0, INSET, 2)
    chrome = _Chrome(window, glass)
    chrome.lock_all()
    chrome.seat_lights()
    window._mac_glass = glass
    window._mac_chrome = chrome
    if hasattr(window, "_dock_tab_bars"):       # the model window's drawer
        from views import mac_inspector
        mac_inspector.install(window)
    apply_palette(window)
    from views.theme import style
    style(window, _window_sheet(window, editing=False))
    return glass


def _window_sheet(window, editing: bool) -> str:
    sheet = WINDOW_SHEET
    if getattr(window, "_mac_inspector", None) is not None:
        from views import mac_inspector
        sheet += mac_inspector.SHEET
    return sheet + (EDIT_SHEET if editing else "")


def seat_lights(window) -> None:
    """Keep the traffic lights' room first in the top row (after a layout
    restore or a toolbar repack). A no-op without glass."""
    chrome = getattr(window, "_mac_chrome", None)
    if chrome is not None:
        chrome.lock_all()
        chrome.seat_lights()


def customizing(window) -> bool:
    chrome = getattr(window, "_mac_chrome", None)
    return chrome is not None and chrome.editing


def set_customizing(window, on: bool) -> None:
    chrome = getattr(window, "_mac_chrome", None)
    if chrome is not None:
        chrome.set_editing(on)


#: The window's chrome over glass: no frames around the toolbars and no
#: grips on them (they are locked; see EDIT_SHEET), borderless toolbar
#: buttons, the dock splitters invisible, the panels see-through.
CHROME_SHEET = (
    "QMainWindow::separator {{ background: transparent;"
    " width: 6px; height: 6px; }}"
    "QToolBar {{ background: transparent; border: none; spacing: 0px;"
    " padding: 2px 6px; }}"
    "QToolBar:vertical {{ padding: 8px 8px; }}"
    "QToolBar::separator {{ background: rgba({ink_rgb}, 40);"
    " width: 1px; height: 1px; margin: 6px 4px; }}"
    # Toolbar buttons: borderless, a rounded fill when hovered or on —
    # never Fusion's square bevel.
    # Each its own pill with a gap to the next and air above and below,
    # so two buttons on side by side never fuse into one block (Maxence,
    # 07-11); the width per button is what padding + spacing took before.
    "QToolBar QToolButton {{ background: transparent; border: none;"
    " border-radius: 7px; padding: 0px; margin: 2px 1px; }}"
    "QToolBar QToolButton:hover {{ background: rgba({ink_rgb}, 20); }}"
    "QToolBar QToolButton:pressed {{ background: rgba({ink_rgb}, 40); }}"
    "QToolBar QToolButton:checked {{ background: rgba({accent_rgb}, 52); }}"
    "QToolBar QToolButton:checked:hover {{"
    " background: rgba({accent_rgb}, 72); }}"
    "QToolBar QToolButton::menu-button {{ border: none; width: 12px; }}"
    "QToolBarExtension {{ border-radius: 8px; }}"
    # Under a stylesheet Qt stops handing the window's palette down, so
    # what must let the glass through says so here: the panels' scroll
    # areas and the pages in them. Lists and tables keep a faint veil, as
    # AppKit's boxed lists.
    "QDockWidget, QDockWidget > QWidget {{ background: transparent; }}"
    "QAbstractScrollArea {{ background: transparent; }}"
    "QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport,"
    " QScrollArea > QWidget#qt_scrollarea_viewport > QWidget"
    " {{ background: transparent; }}"
    "QAbstractItemView {{ background: rgba({ink_rgb}, 10); border: none;"
    " border-radius: 6px; }}"
    "QDockWidget QTreeView {{ background: transparent; }}"
    "QStatusBar {{ background: transparent; }}"
    "QStatusBar::item {{ border: none; }}"
)

#: The controls in the macOS idiom — pop-up buttons with a double chevron,
#: tabs as pills, slim scroll bars with no arrows (AppKit's overlay style),
#: rounded borderless buttons, fields with the accent as focus ring,
#: steppers. On glass windows and, opaque, on every dialog.
CONTROLS_SHEET = (
    "QComboBox {{ background: rgba({ink_rgb}, 22); border: none;"
    " border-radius: 7px; padding: 1px 4px; min-height: 20px; }}"
    "QComboBox:hover {{ background: rgba({ink_rgb}, 34); }}"
    "QComboBox:focus {{ border: 2px solid rgba({accent_rgb}, 200);"
    " padding: -1px 2px; }}"
    "QComboBox::drop-down {{ border: none; width: 16px; }}"
    "QComboBox::down-arrow {{ image: url({combo_arrow});"
    " width: 9px; height: 14px; }}"
    # Every tab bar as a row of pills (the trays', a panel's tab widget,
    # the sheets'): AppKit's segmented look, no frame around the pages.
    "QTabBar {{ background: transparent; qproperty-drawBase: 0; }}"
    "QTabBar::tab {{ background: transparent; border: none;"
    " border-radius: 7px; padding: 3px 10px; margin: 4px 1px 2px 1px; }}"
    "QTabBar::tab:selected {{ background: rgba({ink_rgb}, 36); }}"
    "QTabBar::tab:!selected:hover {{ background: rgba({ink_rgb}, 16); }}"
    "QTabWidget::pane {{ border: none; background: transparent; top: 0; }}"
    "QScrollBar:vertical {{ background: transparent; width: 11px;"
    " margin: 2px 1px 2px 0; border: none; }}"
    "QScrollBar:horizontal {{ background: transparent; height: 11px;"
    " margin: 0 2px 1px 2px; border: none; }}"
    "QScrollBar::handle {{ background: rgba({ink_rgb}, 70);"
    " border-radius: 3px; margin: 2px; }}"
    "QScrollBar::handle:hover, QScrollBar::handle:pressed {{"
    " background: rgba({ink_rgb}, 120); border-radius: 4px; margin: 1px; }}"
    "QScrollBar::handle:vertical {{ min-height: 32px; }}"
    "QScrollBar::handle:horizontal {{ min-width: 32px; }}"
    "QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0;"
    " border: none; background: none; }}"
    "QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}"
    # Push buttons and fields: rounded, borderless fills, the accent as
    # the focus ring — AppKit's bezel-less controls on glass.
    "QPushButton {{ background: rgba({ink_rgb}, 22); border: none;"
    " border-radius: 6px; padding: 2px 6px; min-height: 18px; }}"
    "QPushButton:hover {{ background: rgba({ink_rgb}, 34); }}"
    "QPushButton:pressed, QPushButton:checked {{"
    " background: rgba({ink_rgb}, 50); }}"
    "QPushButton:default {{ background: rgb({accent_rgb}); color: white; }}"
    "QPushButton:disabled {{ color: rgba({ink_rgb}, 90); }}"
    # Spin boxes: a field like the line edits, with a stepper's two
    # chevrons instead of Fusion's bevelled arrow buttons.
    "QAbstractSpinBox {{ background: rgba({ink_rgb}, 14);"
    " border: 1px solid rgba({ink_rgb}, 26); border-radius: 6px;"
    " padding: 1px 4px; min-height: 18px; }}"
    "QAbstractSpinBox:focus {{ border: 2px solid rgba({accent_rgb}, 200);"
    " padding: 0 3px; }}"
    "QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{"
    " border: none; background: transparent; width: 14px; }}"
    "QAbstractSpinBox::up-button {{ subcontrol-position: top right;"
    " margin-top: 2px; }}"
    "QAbstractSpinBox::down-button {{ subcontrol-position: bottom right;"
    " margin-bottom: 2px; }}"
    "QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover"
    " {{ background: rgba({ink_rgb}, 22); border-radius: 3px; }}"
    "QAbstractSpinBox::up-arrow {{ image: url({spin_up});"
    " width: 9px; height: 7px; }}"
    "QAbstractSpinBox::down-arrow {{ image: url({spin_down});"
    " width: 9px; height: 7px; }}"
    # Tooltips: Qt styles a tip from the stylesheet of the widget it is
    # about (it resets the label's own), so the rule lives here. No box of
    # its own: the AppKit tooltip material behind it is the box.
    "QToolTip {{ background: transparent; border: none; padding: 1px 3px;"
    " color: palette(tooltip-text); }}"
    "QLineEdit {{ background: rgba({ink_rgb}, 14);"
    " border: 1px solid rgba({ink_rgb}, 26); border-radius: 6px;"
    " padding: 2px 6px; }}"
    "QLineEdit:focus {{ border: 2px solid rgba({accent_rgb}, 200);"
    " padding: 1px 5px; }}")

#: A template for views.theme.style.
WINDOW_SHEET = CHROME_SHEET + CONTROLS_SHEET

#: Added while customizing: each capsule shows a grip — a short rounded
#: bar, not Fusion's dots — to drag it by.
EDIT_SHEET = (
    "QToolBar::handle {{ image: none; background: rgba({accent_rgb}, 230);"
    " border-radius: 2px; }}"
    "QToolBar::handle:horizontal {{ width: 4px; margin: 7px 3px 7px 4px; }}"
    "QToolBar::handle:vertical {{ height: 4px; margin: 4px 7px 3px 7px; }}"
)


def glyph(kind: str, dark: bool) -> str:
    """Path of a small chrome glyph, painted once per theme into the temp
    folder (a stylesheet's ``image:`` wants a file): ``close`` — the thin
    × of a tab, as Safari's — or ``updown`` — the double chevron of an
    AppKit pop-up button — or ``up`` / ``down``, the halves of a stepper."""
    import os
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    path = os.path.join(tempfile.gettempdir(),
                        f"ingetrazo-{kind}-{'dark' if dark else 'light'}"
                        f"-{os.getuid()}.png")
    if os.path.exists(path):
        return path
    w, h = {"close": (32, 32), "updown": (18, 28)}.get(kind, (18, 14))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    ink = QColor(255, 255, 255, 200) if dark else QColor(0, 0, 0, 180)
    p.setPen(QPen(ink, 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "close":
        p.drawLine(QPointF(10, 10), QPointF(22, 22))
        p.drawLine(QPointF(22, 10), QPointF(10, 22))
    elif kind == "updown":
        p.drawPolyline([QPointF(4, 10), QPointF(9, 5), QPointF(14, 10)])
        p.drawPolyline([QPointF(4, 18), QPointF(9, 23), QPointF(14, 18)])
    elif kind == "up":
        p.drawPolyline([QPointF(4, 10), QPointF(9, 5), QPointF(14, 10)])
    else:                                               # "down"
        p.drawPolyline([QPointF(4, 4), QPointF(9, 9), QPointF(14, 4)])
    p.end()
    img.setDevicePixelRatio(2.0)
    img.save(path)
    return path


def active(window) -> bool:
    """Whether ``window`` (or the window it lives in) sits on glass."""
    top = window.window() if window is not None else None
    return getattr(top, "_mac_glass", None) is not None


def apply_palette(window) -> None:
    """The window's palette with the chrome's surfaces see-through, so the
    glass behind shows; fields and lists keep a light veil to stay legible.
    Re-applied by views.theme on every theme change. Dialogs and menus are
    separate windows and keep the opaque application palette."""
    glass = getattr(window, "_mac_glass", None)
    if glass is None:
        return
    glass.retint()
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    p = QPalette(QApplication.palette())
    dark = p.color(QPalette.Window).lightness() < 128
    veil = QColor(255, 255, 255, 14) if dark else QColor(255, 255, 255, 110)
    clear = QColor(0, 0, 0, 0)
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        p.setColor(group, QPalette.Window, clear)
        p.setColor(group, QPalette.Base, veil)
        p.setColor(group, QPalette.AlternateBase, veil)
        p.setColor(group, QPalette.Button,
                   QColor(255, 255, 255, 22) if dark
                   else QColor(255, 255, 255, 150))
    window.setPalette(p)
    # A dock that has ever been a floating window stops inheriting the
    # window's palette (Qt does not propagate to windows): set it on each.
    from PySide6.QtWidgets import QDockWidget
    for dock in window.findChildren(QDockWidget):
        dock.setPalette(p)
    # Stylesheets resolved palette(window) when they were polished, with the
    # opaque palette: polish them again (see views.theme._repolish).
    from PySide6.QtWidgets import QWidget
    for w in [window, *window.findChildren(QWidget)]:
        if w.isWindow() and w is not window:
            continue
        if w.objectName() == "mac_customize_bar":
            w.setPalette(QApplication.palette())
        sheet = w.styleSheet()
        if sheet:
            w.setStyleSheet(sheet)
