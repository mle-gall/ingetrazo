"""The side drawer's navigation on the macOS glass chrome: an inspector.

On Liquid Glass (views/mac_glass.py) the row of tabs over the sidebar
becomes what Xcode's and Keynote's inspectors have: one segmented control
of panel icons — a recessed track, the open panel a raised segment — with
the open panel's name as a header under it. The tabs' names are their
tooltips.

It is still Qt's own tab bar, only painted differently and given square
tabs: clicking, dragging a tab out or across, the right-click menu, the
«+» of Add panels and everything main_window does with those bars keep
working as they are. Without glass none of this runs.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QCursor, QFont, QPainter, QPainterPath,
                           QPalette, QPen)
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QTabBar

#: A segment: square enough for a 16 pt glyph with air around it.
SEGMENT_W, SEGMENT_H = 34, 28
TRACK_RADIUS = 9.0

_PROP = "mac_inspector"


def _dark() -> bool:
    return QApplication.palette().color(QPalette.Window).lightness() < 128


def _ink(alpha: int) -> QColor:
    return QColor(255, 255, 255, alpha) if _dark() else QColor(0, 0, 0, alpha)


# ---- the panels' glyphs --------------------------------------------------------
# Line glyphs in one weight on a 16-unit grid, in the manner of SF Symbols,
# so the row reads as one family whatever the panels are.

def _g_properties(p: QPainter) -> None:          # slider.horizontal.3
    for y, knob in ((4, 11), (8, 5), (12, 9)):
        p.drawLine(QPointF(2, y), QPointF(14, y))
        p.save()
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(knob, y), 1.6, 1.6)
        p.restore()


def _g_browser(p: QPainter) -> None:             # list.bullet.indent
    for x, y, w in ((2, 3.5, 12), (5, 8, 9), (5, 12.5, 9)):
        p.drawEllipse(QPointF(x, y), 0.9, 0.9)
        p.drawLine(QPointF(x + 2.5, y), QPointF(x + w - 0.5, y))
    p.drawLine(QPointF(2, 5), QPointF(2, 12.5))
    p.drawLine(QPointF(2, 8), QPointF(3.5, 8))
    p.drawLine(QPointF(2, 12.5), QPointF(3.5, 12.5))


def _g_layers(p: QPainter) -> None:              # square.3.layers
    for dy in (0, 3.5, 7):
        path = QPainterPath()
        path.moveTo(8, 1.5 + dy)
        path.lineTo(14.5, 4.5 + dy)
        path.lineTo(8, 7.5 + dy)
        path.lineTo(1.5, 4.5 + dy)
        path.closeSubpath()
        p.drawPath(path)


def _g_bim(p: QPainter) -> None:                 # building.2
    p.drawRect(QRectF(2.5, 4, 6, 10))
    p.drawRect(QRectF(8.5, 7, 5, 7))
    for y in (6.5, 9, 11.5):
        p.drawLine(QPointF(4.5, y), QPointF(6.5, y))


def _g_terrain(p: QPainter) -> None:             # mountain.2
    path = QPainterPath()
    path.moveTo(1, 13.5)
    path.lineTo(6, 5)
    path.lineTo(9, 10)
    path.lineTo(11, 7)
    path.lineTo(15, 13.5)
    path.closeSubpath()
    p.drawPath(path)


def _g_ai(p: QPainter) -> None:                  # sparkles
    def star(cx, cy, r):
        path = QPainterPath()
        path.moveTo(cx, cy - r)
        path.quadTo(cx, cy, cx + r, cy)
        path.quadTo(cx, cy, cx, cy + r)
        path.quadTo(cx, cy, cx - r, cy)
        path.quadTo(cx, cy, cx, cy - r)
        p.drawPath(path)
    star(6.5, 9, 5.5)
    star(12.5, 4, 2.6)


def _g_render(p: QPainter) -> None:              # camera.aperture
    p.drawEllipse(QPointF(8, 8), 6.5, 6.5)
    for a in range(6):
        from math import cos, radians, sin
        t = radians(a * 60)
        p.drawLine(QPointF(8 + 2.6 * cos(t), 8 + 2.6 * sin(t)),
                   QPointF(8 + 6.4 * cos(t + 0.9), 8 + 6.4 * sin(t + 0.9)))


def _g_solid(p: QPainter) -> None:               # cube + check
    path = QPainterPath()
    path.moveTo(8, 1.5)
    path.lineTo(14, 4.5)
    path.lineTo(14, 11.5)
    path.lineTo(8, 14.5)
    path.lineTo(2, 11.5)
    path.lineTo(2, 4.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(2, 4.5), QPointF(8, 7.5))
    p.drawLine(QPointF(14, 4.5), QPointF(8, 7.5))
    p.drawLine(QPointF(8, 7.5), QPointF(8, 14.5))


#: objectName (or a piece of it) → glyph. First match wins.
_GLYPHS = (
    ("tray_properties", _g_properties),
    ("tray_project_browser", _g_browser),
    ("tray_layers", _g_layers),
    ("tray_bim", _g_bim),
    ("tray_georef", _g_terrain),
    ("solid", _g_solid),
    ("render", _g_render),
    ("extension_ai", _g_ai),
    ("_ai", _g_ai),
)


def _glyph_for(dock):
    name = dock.objectName() if dock is not None else ""
    for key, draw in _GLYPHS:
        if key in name:
            return draw
    return None


def _paint_glyph(p: QPainter, dock, centre: QPointF, color: QColor) -> None:
    draw = _glyph_for(dock)
    p.save()
    if draw is None:
        # An extension's panel we have no drawing for: its initials in a
        # rounded square, in the same weight.
        title = dock.windowTitle() if dock is not None else "?"
        letters = "".join(w[0] for w in title.split()[:2]).upper() or "?"
        p.setPen(QPen(color, 1.3))
        box = QRectF(centre.x() - 8, centre.y() - 8, 16, 16)
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        f = QFont(p.font())
        f.setPixelSize(8 if len(letters) > 1 else 9)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(box, Qt.AlignCenter, letters)
    else:
        p.translate(centre.x() - 8, centre.y() - 8)
        pen = QPen(color, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        draw(p)
    p.restore()


# ---- the segmented control ----------------------------------------------------

class _Painter(QObject):
    """Paints an adopted tab bar as an icon segmented control, in place of
    Qt's own painting of it."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window

    def _docks_by_title(self) -> dict:
        return {d.windowTitle(): d
                for d in self._window.findChildren(QDockWidget)}

    def eventFilter(self, bar, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Paint:
            try:
                self._paint(bar)
            except RuntimeError:
                return False
            return True
        if event.type() in (QEvent.HoverMove, QEvent.HoverLeave,
                            QEvent.Leave):
            bar.update()
        return False

    def _paint(self, bar: QTabBar) -> None:
        n = bar.count()
        if n == 0:
            return
        rects = [QRectF(bar.tabRect(i)) for i in range(n)]
        track = rects[0].united(rects[-1]).adjusted(0, 1, 0, -1)
        docks = self._docks_by_title()
        hover = bar.tabAt(bar.mapFromGlobal(QCursor.pos())) \
            if bar.underMouse() else -1
        p = QPainter(bar)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(_ink(16))
        p.drawRoundedRect(track, TRACK_RADIUS, TRACK_RADIUS)
        current = bar.currentIndex()
        for i, r in enumerate(rects):
            seg = r.adjusted(2, 3, -2, -3)
            if i == current:
                # The raised segment: a lighter pill with a soft shadow.
                p.setBrush(QColor(0, 0, 0, 50))
                p.drawRoundedRect(seg.translated(0, 0.8), 7, 7)
                p.setBrush(QColor(255, 255, 255, 46) if _dark()
                           else QColor(255, 255, 255, 235))
                p.drawRoundedRect(seg, 7, 7)
            elif i == hover:
                p.setBrush(_ink(14))
                p.drawRoundedRect(seg, 7, 7)
        for i, r in enumerate(rects):
            dock = docks.get(bar.tabText(i))
            ink = _ink(235 if i == current else 150)
            _paint_glyph(p, dock, r.center(), ink)
        p.end()


class _Header(QLabel):
    """The open panel's name under the segmented control."""

    def __init__(self, dock) -> None:
        super().__init__(dock.windowTitle(), dock)
        self.setObjectName("mac_inspector_header")
        dock.windowTitleChanged.connect(self.setText)
        f = self.font()
        f.setPointSizeF(f.pointSizeF() + 2)
        f.setWeight(QFont.Bold)
        self.setFont(f)
        self.setContentsMargins(12, 6, 12, 4)


#: The «Add panels» button after the segments: a round glass button.
PLUS_SHEET = (
    "QToolButton {{ border: none; border-radius: 10px;"
    " background: rgba({ink_rgb}, 16); font-weight: bold;"
    " font-size: 14px; padding: 0 0 2px 0; }}"
    "QToolButton:hover {{ background: rgba({ink_rgb}, 34); }}"
    "QToolButton:pressed {{ background: rgba({ink_rgb}, 50); }}"
)


class Inspector(QObject):
    """Keeps every sidebar tab bar of a glass window an inspector."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._painter = _Painter(window)

    @staticmethod
    def _dress_plus(bar) -> None:
        from PySide6.QtWidgets import QToolButton
        btn = bar.findChild(QToolButton, "add_panels_button")
        if btn is not None and not btn.property(_PROP):
            btn.setProperty(_PROP, True)
            from views.theme import style
            style(btn, PLUS_SHEET)

    def dress(self) -> None:
        """Adopt new tab bars and give tabbed docks their header. Called
        whenever main_window has re-styled its dock tabs."""
        w = self._window
        for bar in w.findChildren(QTabBar):
            mine = bar.parentWidget() is w \
                or type(bar).__name__ == "_DockTitleTab"
            if mine and not bar.property(_PROP):
                bar.setProperty(_PROP, True)
                bar.setAttribute(Qt.WA_Hover, True)
                bar.setUsesScrollButtons(True)
                bar.installEventFilter(self._painter)
                bar.style().unpolish(bar)
                bar.style().polish(bar)
                bar.update()
            if mine:
                self._dress_plus(bar)
        from PySide6.QtWidgets import QWidget
        for dock in w.findChildren(QDockWidget):
            if dock.parentWidget() is not w or dock.isFloating():
                continue
            title = dock.titleBarWidget()
            # The empty strip main_window gives a tabbed dock: our header.
            if title is not None and type(title) is QWidget \
                    and not title.children():
                dock.setTitleBarWidget(_Header(dock))
                title.deleteLater()


#: The tabs as square segments; their text is never painted (see _Painter)
#: but stays the tab's tooltip and what main_window matches docks by.
SHEET = (
    f"QTabBar[{_PROP}=\"true\"] {{{{ background: transparent; }}}}"
    f"QTabBar[{_PROP}=\"true\"]::tab {{{{ width: {SEGMENT_W}px;"
    f" height: {SEGMENT_H}px; margin: 6px 0 2px 0; padding: 0;"
    " border: none; background: transparent; color: transparent; }}"
)


def install(window):
    """An Inspector for ``window`` (mac_glass.install calls it)."""
    inspector = Inspector(window)
    window._mac_inspector = inspector
    inspector.dress()
    return inspector


def dress(window) -> None:
    """Re-dress after main_window rebuilt its dock tabs; no-op without
    glass."""
    inspector = getattr(window, "_mac_inspector", None)
    if inspector is not None:
        inspector.dress()
