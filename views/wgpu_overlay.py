"""Rasterize logical-pixel tool primitives offscreen for native compositing.

The Metal widget cannot host QPainter. Painting into a straight-alpha RGBA
image preserves Qt text and glyph rendering without sibling window stacking.
"""
from dataclasses import dataclass
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF


@dataclass(frozen=True)
class Primitive:
    kind: str
    points: tuple
    color: str = "#00dfff"
    width: float = 1.5
    text: str = ""
    fill: str | None = None
    dash: tuple = ()


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
            pen = QPen(QColor(primitive.color), primitive.width)
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
    """Endpoint square, midpoint triangle, and circular edge/face marker."""
    x, y = point
    if kind in ("vertex", "endpoint"):
        return Primitive("rectangle", ((x-4, y-4), (x+4, y+4)), color)
    if kind == "midpoint":
        return Primitive("polygon", ((x, y-5), (x-5, y+4), (x+5, y+4)), color)
    return Primitive("point", ((x, y),), color, 4)


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
