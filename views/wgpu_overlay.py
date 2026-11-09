"""Rasterize logical-pixel tool primitives offscreen for native compositing.

The Metal widget cannot host QPainter. Painting into a straight-alpha RGBA
image preserves Qt text and glyph rendering without sibling window stacking.
"""
from dataclasses import dataclass
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF


@dataclass(frozen=True)
class Primitive:
    kind: str
    points: tuple
    color: str = "#00dfff"
    width: float = 1.5
    text: str = ""
    fill: str | None = None
    dash: tuple = ()
    pen_style: Qt.PenStyle = Qt.SolidLine
    snap_kind: str = ""


def rasterize(primitives, width, height, scale, annotations=None):
    """Return an owned image at physical resolution, drawing in logical units."""
    image = QImage(max(1, int(width * scale)), max(1, int(height * scale)),
                   QImage.Format_RGBA8888)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        if annotations is not None:
            annotations(painter)
        for primitive in primitives:
            if primitive.kind == "snap":
                from types import SimpleNamespace
                c = QColor(primitive.color)
                snap = SimpleNamespace(kind=primitive.snap_kind, point=primitive.points[0],
                                       color=c.getRgbF()[:3], guide=None, guides=(),
                                       axis=None, label=primitive.text, context=None)
                draw_snap_indicator(painter, snap, lambda p: p,
                                    lambda a, b: (a, b), labels=False)
                continue
            pen = QPen(QColor(primitive.color), primitive.width, primitive.pen_style)
            if primitive.dash:
                pen.setDashPattern(primitive.dash)
                pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.setBrush(QColor(primitive.fill) if primitive.fill else Qt.NoBrush)
            points = [QPointF(*p) for p in primitive.points]
            if primitive.kind == "polyline":
                painter.drawPolyline(QPolygonF(points))
            elif primitive.kind == "polygon":
                painter.drawPolygon(QPolygonF(points))
            elif primitive.kind == "rectangle":
                painter.drawRect(QRectF(points[0], points[1]).normalized())
            elif primitive.kind == "point":
                painter.drawEllipse(points[0], primitive.width, primitive.width)
            elif primitive.kind == "text":
                painter.drawText(points[0], primitive.text)
            else:
                raise ValueError(f"Unknown overlay primitive: {primitive.kind}")
    finally:
        painter.end()
    return image


def pixels(image):
    """Borrow contiguous RGBA storage; the caller retains the image on upload."""
    return np.frombuffer(image.constBits(), dtype=np.uint8)


def snap_glyph(point, kind, color="#00dfff"):
    """Return one haloed marker; color accepts a Qt color string or QColor.

    P1 should prefer draw_snap_indicator for the full SnapResult, including
    guide colors, contextual/translated labels, and axis marker suppression.
    The legacy vertex alias still means endpoint.
    """
    return Primitive("snap", (point,), color, snap_kind=(
        "endpoint" if kind == "vertex" else kind))


def selection_rectangle(start, end, *, zoom=False):
    """Return GL's direction-sensitive box in logical pixels (no drag threshold).

    P1 calls this after its drag threshold, with unsorted start/end tuples.
    Set zoom=True for Zoom Window; append the returned Primitive.
    """
    crossing = end[0] < start[0]
    color = "#f37329" if zoom else ("#289e5c" if crossing else "#3366c7")
    alpha = "1a" if zoom else "1c"
    return Primitive("rectangle", (start, end), color, 1.5,
                     fill="#" + alpha + color[1:],
                     pen_style=Qt.DashLine if zoom or crossing else Qt.SolidLine)


def axes(origin, directions, length=32):
    """Projected camera axes; callers supply three normalized screen vectors."""
    result = []
    for label, color, direction in zip("XYZ", ("#ff5555", "#55dd55", "#5599ff"), directions):
        x, y = origin
        dx, dy = direction
        norm = max(math.hypot(dx, dy), 1e-12)
        end = (x + length*dx/norm, y + length*dy/norm)
        result.extend((Primitive("polyline", (origin, end), color),
                       Primitive("text", (end,), color, text=label)))
    return result


def draw_snap_indicator(painter, snap, project, clip_line, *, labels=True):
    """Paint a full SnapResult using GL's glyphs, halos, guides and labels.

    P1 calls from the rasterize annotation callback, passing its world-to-logical
    pixel projector and a clipped screen-line function (a,b)->(a,b) or None.
    Colors come from SnapResult, including group/context and guide overrides.
    No marker or guide is painted for axis/axis_inference snaps.
    """
    from views.viewport import Viewport
    from core.i18n import tr
    # Axis-lock and inference state is conveyed by the coloured rubber
    # band; no badge follows the cursor along the lock line. Only the
    # discrete point snaps get a marker.
    if snap.kind in ("axis_inference", "axis"):
        return
    pixel = project(snap.point)
    if pixel is None:
        return
    r, g, b = snap.color
    color = QColor.fromRgbF(r, g, b, 1.0)
    # Dashed guide line (the extension inference shows the edge's dashed
    # continuation to the cursor).
    if snap.guide is not None:
        gp0 = project(snap.guide[0])
        gp1 = project(snap.guide[1])
        if gp0 is not None and gp1 is not None:
            # A snap can colour its guide differently from the marker (the
            # 'from point' guide is axis-coloured while the point is green).
            gc = snap.guide_color if snap.guide_color is not None else (r, g, b)
            dash = QPen(QColor.fromRgbF(gc[0], gc[1], gc[2], 0.9), 2.0, Qt.DashLine)
            painter.setPen(dash)
            vis = clip_line(gp0, gp1)
            if vis is not None:
                painter.drawLine(QPointF(*vis[0]), QPointF(*vis[1]))
    for ga, gb_, gc in (snap.guides or []):
        gp0 = project(ga)
        gp1 = project(gb_)
        if gp0 is not None and gp1 is not None:
            painter.setPen(QPen(QColor.fromRgbF(gc[0], gc[1], gc[2], 0.9), 2.0, Qt.DashLine))
            vis = clip_line(gp0, gp1)
            if vis is not None:
                painter.drawLine(QPointF(*vis[0]), QPointF(*vis[1]))
    # A white halo under the marker lifts it off busy geometry, then
    # the coloured marker on top — bigger and bolder than before so the
    # snap point reads at a glance (a common request: the dots were too
    # small to aim with).
    halo = QPen(QColor(255, 255, 255, 230), 4.5)
    mark = QPen(color, 2.6)
    painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
    px, py = pixel
    if snap.kind == "intersection":
        # X marker at the crossing (drawn line × projected guide).
        for pen in (halo, mark):
            painter.setPen(pen)
            painter.drawLine(QPointF(px - 8, py - 8), QPointF(px + 8, py + 8))
            painter.drawLine(QPointF(px - 8, py + 8), QPointF(px + 8, py - 8))
    elif snap.kind == "center":
        # The centre of a circle: a filled dot.
        painter.setPen(halo)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
        painter.setPen(mark)
        painter.setBrush(QColor.fromRgbF(r, g, b, 0.85))
        painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
    elif snap.kind in ("endpoint", "origin", "component_origin", "on_edge",
                       "on_axis", "intersection_edge", "intersection_face",
                       "on_line", "extension", "from_point", "aligned",
                       "tangent"):
        rect = QRectF(px - 7, py - 7, 14, 14)
        painter.setPen(halo)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)
        painter.setPen(mark)
        painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
        painter.drawRect(rect)
    elif snap.kind in ("midpoint", "arc_midpoint"):
        # Cyan diamond.
        diamond = QPolygonF([
            QPointF(px, py - 9), QPointF(px + 9, py),
            QPointF(px, py + 9), QPointF(px - 9, py),
        ])
        painter.setPen(halo)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolygon(diamond)
        painter.setPen(mark)
        painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
        painter.drawPolygon(diamond)
    elif snap.kind == "on_face":
        painter.setPen(halo)
        painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
        painter.setPen(mark)
        painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
    elif snap.kind == "close":
        painter.setPen(halo)
        painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
        painter.setPen(mark)
        painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
    elif snap.kind in ("reference", "through_point", "perp_face"):
        painter.setPen(halo)
        painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
        painter.setPen(mark)
        painter.drawEllipse(QPointF(px, py), 6.5, 6.5)

    # Tooltip text next to the marker ("On Edge", etc.).
    label = Viewport._SNAP_LABELS.get(snap.kind) if labels else None
    if snap.kind == "aligned" and snap.axis == "z":
        label = "Level with point"
    if label:
        label = tr(label)
    if labels and getattr(snap, "label", None):
        label = snap.label               # an extension's own words
    if label:
        ctx_ = getattr(snap, "context", None)
        if ctx_ == "component":
            label += " " + tr("in component")
        elif ctx_ == "group":
            label += " " + tr("in group")
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QPen(QColor(255, 255, 255, 220)))
        painter.drawText(QPointF(px + 11, py + 17), label)
        painter.setPen(QPen(color))
        painter.drawText(QPointF(px + 10, py + 16), label)
