# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Opening returns to the renderer before optional document work runs."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats import igz
from views.main_window import MainWindow


def test_open_does_not_prepare_before_picture(tmp_path, monkeypatch):
    monkeypatch.setenv('INGETRAZO_WGPU', '0')
    path = tmp_path/'empty.igz'
    igz.save_scene(Scene(), path)
    win = MainWindow(defer_extensions=True)
    order = []
    monkeypatch.setattr(win.viewport, 'prepare_drawing', lambda *a: order.append('prepare'))
    monkeypatch.setattr(win, '_after_links_loaded', lambda: order.append('links'))
    monkeypatch.setattr(win, 'settle_heap', lambda: order.append('heap'))
    try:
        assert win.open_path(path)
        assert order == []
        assert win._doc._awaiting_picture
        win.viewport.frameSwapped.emit()  # stale swap, no loaded chunks yet
        assert win._doc._awaiting_picture
        assert order == []
        order.append('frame')
        win.viewport._edges_version = win.viewport.scene.version
        win.viewport.frameSwapped.emit()
        assert not win._doc._awaiting_picture
        # Use a bounded Qt loop to drain paced jobs without needing a GL driver.
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        assert order == ['frame', 'links', 'heap']
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        win.deleteLater()
        QApplication.processEvents()


def test_previous_metal_frame_cannot_release_loaded_document(monkeypatch):
    from types import SimpleNamespace
    from core import renderer_settings
    doc = SimpleNamespace(_renderer_wgpu=True, _resident_scene_ready=False,
                          _awaiting_picture=True, _renderer_starting=True)
    calls = []
    monkeypatch.setattr(renderer_settings, 'first_frame', lambda: calls.append('guard'))
    host = SimpleNamespace(_drain_document_startup=lambda d: calls.append('work'))
    MainWindow._document_first_frame(host, doc)
    assert calls == []
    assert doc._awaiting_picture
    doc._resident_scene_ready = True
    host._opening_document = True
    MainWindow._document_first_frame(host, doc)
    assert calls == []
    host._opening_document = False
    MainWindow._document_first_frame(host, doc)
    assert calls == ['guard', 'work']
    assert not doc._awaiting_picture
