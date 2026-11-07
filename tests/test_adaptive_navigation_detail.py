"""Navigation feedback is temporary and absent from exports."""
from PySide6.QtGui import QMatrix4x4
from views import viewport as viewport_module
from tests.test_rendering_surface_regressions import viewport
from tests.test_instanced_view_superset import _window, _close, _look, _place, _box_mesh, _drawn


def test_navigation_settles_and_respects_precision_contexts(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(viewport_module._time_mod, 'monotonic', lambda: now[0])
    win = _window()
    try:
        vp = win.viewport
        vp._inst_pool = (None, [None] * 2000)
        a = QMatrix4x4(); b = QMatrix4x4(); b.translate(1, 0, 0)
        assert vp._navigation_detail(a, 'shaded') is False
        assert vp._navigation_detail(b, 'shaded') is True
        assert vp._nav_detail_timer.isActive()
        now[0] += .2
        assert vp._navigation_detail(b, 'shaded') is True
        now[0] += .2
        assert vp._navigation_detail(b, 'shaded') is False
        assert vp._navigation_detail(a, 'shaded') is True
        vp._export_size = (800, 600)
        assert vp._navigation_detail(b, 'shaded') is False
        vp._export_size = None
        assert vp._navigation_detail(b, 'wireframe') is False
        assert vp._navigation_detail(a, 'hidden_line') is False
        vp.scene.selection.add(object())
        assert vp._navigation_detail(a, 'shaded') is False
        vp.scene.selection.clear()
        vp._inst_pool = (None, [None] * 10)
        assert vp._navigation_detail(b, 'shaded') is False
    finally:
        _close(win)


def test_navigation_keeps_all_face_batches_intact():
    win = _window()
    try:
        vp = win.viewport
        _look(vp, 10)
        _place(vp, _box_mesh(.025), 0, 0)
        _place(vp, _box_mesh(2), 1, 0)
        vp.scene.version += 1
        original_groups = tuple(vp.scene.groups)
        full = _drawn(vp)
        full_batches = vp._frame_instanced
        assert len(full) == 2
        vp._nav_fast_feedback = True
        reduced = _drawn(vp)
        assert reduced == full
        assert all(batch is full_batches[key]
                   for key, batch in vp._frame_instanced.items())
        vp._export_size = (800, 600)
        assert _drawn(vp) == full
        vp._export_size = None
        vp._nav_fast_feedback = False
        assert _drawn(vp) == full
        assert tuple(vp.scene.groups) == original_groups
    finally:
        _close(win)


def test_settle_timer_repaints_full_detail_without_another_input(viewport, monkeypatch):
    from PySide6.QtTest import QTest
    from tests.test_rendering_surface_regressions import pixels, _app
    import numpy as np
    vp = viewport
    mesh = _box_mesh(.025)
    for i in range(2000):
        _place(vp, mesh, (i % 50) * .04 - 1, (i // 50) * .04 - .8)
    _place(vp, _box_mesh(2), -3, 0)
    _look(vp, 10)
    vp.scene.version += 1
    vp.update(); _app.processEvents()
    vp.camera.orbit(15, 2, vp.height())
    vp.update(); _app.processEvents()
    assert vp._nav_fast_feedback is True
    QTest.qWait(450)
    assert vp._nav_fast_feedback is False
    settled = pixels(vp.grabFramebuffer())
    monkeypatch.setattr(vp, '_navigation_detail', lambda *args: False)
    vp._frame_cache = None
    vp.update(); _app.processEvents()
    assert np.array_equal(settled, pixels(vp.grabFramebuffer()))

