# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""macOS hands a double-clicked/Open-With document to the running app as a
QFileOpenEvent, never as argv[1] (unlike Linux/Windows) — _App.event() is
the seam that catches it and routes it through the same _open_document_in
the argv path and the single-instance socket already use."""
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QFileOpenEvent

from main import _App


class _StubWindow:
    def __init__(self):
        self.opened: list[Path] = []

    def open_path(self, path):
        self.opened.append(path)


def _file_open_event(path: str) -> QFileOpenEvent:
    return QFileOpenEvent(path)


class TestMacFileOpenEvent:
    def test_opens_straight_into_an_existing_window(self, tmp_path):
        doc = tmp_path / "model.igz"
        doc.write_text("{}")
        window = _StubWindow()
        app_stub = SimpleNamespace(open_window=window, pending_open_path=None)

        handled = _App.event(app_stub, _file_open_event(str(doc)))

        assert handled is True
        assert window.opened == [doc]
        assert app_stub.pending_open_path is None

    def test_queues_the_path_when_no_window_exists_yet(self, tmp_path):
        # A cold launch: the Apple Event can arrive before MainWindow() runs.
        doc = tmp_path / "model.igz"
        doc.write_text("{}")
        app_stub = SimpleNamespace(open_window=None, pending_open_path=None)

        handled = _App.event(app_stub, _file_open_event(str(doc)))

        assert handled is True
        assert app_stub.pending_open_path == doc

    def test_skp_goes_through_the_same_seam(self, tmp_path):
        doc = tmp_path / "model.skp"
        doc.write_bytes(b"")
        window = SimpleNamespace(import_skp_path=lambda p: True,
                                  _on_zoom_extents=lambda: None)
        calls = []
        window.import_skp_path = lambda p: (calls.append(p) or True)
        app_stub = SimpleNamespace(open_window=window, pending_open_path=None)

        _App.event(app_stub, _file_open_event(str(doc)))
        # _open_document_in defers .skp import to the next event-loop tick
        # (see main.py) — pump it once so the stub records the call.
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.instance().processEvents()

        assert calls == [doc]


    def test_a_command_line_path_is_not_opened_twice(self, tmp_path):
        # Qt's Cocoa plugin also delivers argv paths as FileOpen events; the
        # argv path is opened by main() once the window is up, so the event
        # for the same file is swallowed — once. A later event (Open With
        # on the same file) opens it again as usual.
        doc = tmp_path / "model.igz"
        doc.write_text("{}")
        window = _StubWindow()
        app_stub = SimpleNamespace(open_window=window, pending_open_path=None,
                                   argv_paths={doc.resolve()})

        assert _App.event(app_stub, _file_open_event(str(doc))) is True
        assert window.opened == []
        assert _App.event(app_stub, _file_open_event(str(doc))) is True
        assert window.opened == [doc]

    def test_argv_paths_are_collected_from_the_command_line(self, tmp_path):
        doc = tmp_path / "model.igz"
        doc.write_text("{}")
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            import pytest
            pytest.skip("a QApplication already exists in this process")
        app = _App(["main.py", "--new-window", str(doc)])
        try:
            assert doc.resolve() in app.argv_paths
        finally:
            app.quit()
