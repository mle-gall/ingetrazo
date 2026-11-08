"""Verify overlay pixels independently of native presentation and GPU access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from views.wgpu_overlay import Primitive, axes, pixels, rasterize, snap_glyph


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_rgba_scale_and_transparent_background(app):
    image = rasterize([Primitive("rectangle", ((10, 10), (30, 30)),
                                 "#ff0000", fill="#ff0000")], 100, 80, 2)
    assert (image.width(), image.height()) == (200, 160)
    assert image.pixelColor(40, 40).getRgb() == (255, 0, 0, 255)
    assert image.pixelColor(150, 100).alpha() == 0
    assert pixels(image).size == 200 * 160 * 4


def test_all_primitives_and_glyphs(app):
    items = [snap_glyph((20, 20), "endpoint"), snap_glyph((40, 40), "midpoint"),
             snap_glyph((60, 60), "on_edge"),
             Primitive("text", ((20, 80),), text="12.5 m"),
             *axes((90, 90), ((1, 0), (0, 1), (-1, -1)))]
    image = rasterize(items, 150, 150, 2)
    assert pixels(image).reshape(-1, 4)[:, 3].sum() > 0
    with pytest.raises(ValueError, match="Unknown"):
        rasterize([Primitive("invalid", ())], 10, 10, 1)
