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
        order.append('frame')
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
