"""views/mac_glass.py: Liquid Glass chrome on macOS 26+.

The AppKit side cannot run here (the suite uses the offscreen platform),
so these pin what must hold everywhere: glass is off and every entry point
is a no-op off cocoa, and the stylesheet templates format with the theme's
tokens in both palettes."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QToolBar

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from views import mac_glass, theme  # noqa: E402


@pytest.fixture
def qapp():
    a = QApplication.instance()
    yield a
    theme.apply_theme(a, theme.DARK)    # the suite's usual chrome


def test_off_without_cocoa(qapp):
    assert qapp.platformName() != "cocoa"
    assert not mac_glass.supported()
    assert not mac_glass.enabled()


def test_entry_points_are_no_ops(qapp):
    w = QMainWindow()
    tb = QToolBar("t", w)
    tb.setMovable(True)
    w.addToolBar(tb)
    assert mac_glass.prepare(w) is False
    assert mac_glass.install(w) is None
    assert not w.testAttribute(Qt.WA_TranslucentBackground)
    mac_glass.seat_lights(w)
    mac_glass.set_customizing(w, True)
    assert not mac_glass.customizing(w)
    assert not mac_glass.active(w)
    assert tb.isMovable()
    mac_glass.apply_palette(w)          # nothing to re-apply
    assert w.palette().color(w.backgroundRole()).alpha() == 255
    w.deleteLater()


def test_sheets_format_in_both_themes(qapp):
    for palette in (theme.dark_palette(), theme.light_palette()):
        qapp.setPalette(palette)
        tokens = theme.tokens()
        for sheet in (mac_glass.WINDOW_SHEET, mac_glass.EDIT_SHEET,
                      mac_glass.MENU_SHEET):
            text = sheet.format(**tokens)
            assert "{" in text and "{{" not in text
    assert theme.tokens()["tab_close"] == ""      # glass off: no glyph


def test_regions_skip_the_title_bar_room(qapp):
    w = QMainWindow()
    lights = QToolBar(w)
    lights.setObjectName(mac_glass.LIGHTS_NAME)
    w.addToolBar(lights)
    tb = QToolBar("Draw", w)
    tb.addAction("x")
    w.addToolBar(tb)
    w.resize(600, 400)
    w.show()
    qapp.processEvents()
    kinds = [kind for _r, _rad, kind in mac_glass.main_window_regions(w)()]
    assert kinds == [mac_glass.TOOLBAR]
    w.close()
    w.deleteLater()


def test_inspector_is_off_without_glass(qapp):
    from views import mac_inspector
    w = QMainWindow()
    mac_inspector.dress(w)              # no inspector installed: no-op
    assert getattr(w, "_mac_inspector", None) is None
    text = mac_inspector.SHEET.format(**theme.tokens())
    assert "::tab" in text and "{{" not in text
    w.deleteLater()


def test_brand_tint_is_translucent():
    for dark in (True, False):
        assert 0 < theme.brand_tint(dark).alpha() < 255
