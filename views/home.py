# SPDX-License-Identifier: GPL-3.0-or-later
"""A small launch surface keeps recents and relocation out of the model view."""
from pathlib import Path
import zipfile
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QListWidgetItem, QLabel, QMessageBox)
from core import recent, renderer_settings
from views.filedialogs import file_dialogs


class Home(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_host = window
        self.setWindowTitle('Home — IngeTrazo')
        self.resize(650, 460)
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for title, fn in [('New document', self.new_document),
                          ('New project…', self.new_project), ('Open…', self.open_dialog)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.lists = {}
        for kind in ('files', 'projects'):
            layout.addWidget(QLabel('Recent ' + kind))
            listing = QListWidget()
            listing.itemDoubleClicked.connect(self.open_item)
            self.lists[kind] = listing
            layout.addWidget(listing)
            pin = QPushButton('Pin / unpin selected ' + kind[:-1])
            pin.clicked.connect(lambda _=False, k=kind: self.pin(k))
            layout.addWidget(pin)
        from core._native import engine
        layout.addWidget(QLabel(f"Engine: {engine()} · Renderer: {renderer_settings.status_text()}"))
        self.refresh()

    def refresh(self):
        for kind, listing in self.lists.items():
            listing.clear()
            for row in recent.entries(kind):
                path = Path(row['path'])
                item = QListWidgetItem(('★ ' if row.get('pinned') else '') + str(path))
                item.setData(Qt.UserRole, row)
                if path.suffix.lower() == '.igz':
                    try:
                        with zipfile.ZipFile(path) as archive:
                            info = archive.getinfo('thumbnail.png')
                            if info.file_size <= 1024 * 1024:
                                pix = QPixmap()
                                pix.loadFromData(archive.read(info), 'PNG')
                                item.setIcon(QIcon(pix))
                    except (OSError, KeyError, zipfile.BadZipFile):
                        pass
                listing.addItem(item)

    def pin(self, kind):
        item = self.lists[kind].currentItem()
        if item is not None:
            row = item.data(Qt.UserRole)
            recent.remember(row['path'], pinned=not row.get('pinned'))
            self.refresh()

    def open_item(self, item):
        return self.open_recent(item.data(Qt.UserRole)['path'])

    def open_recent(self, path):
        original = str(path)
        path = Path(path)
        if not path.is_file():
            located, _ = file_dialogs.getOpenFileName(
                self, 'Locate ' + path.name, '', 'IngeTrazo (*' + path.suffix + ')')
            if not located:
                return False
            path = Path(located)
        if self.window_host.open_path(path):
            recent.remember(path, replace=original)
            self.accept()
            return True
        return False

    def new_document(self):
        self.window_host._on_new()
        from views.units_start_dialog import offer_at_start
        offer_at_start(self.window_host)
        self.accept()

    def new_project(self):
        name, _ = file_dialogs.getSaveFileName(self, 'New project', '', 'Project (*.igzproj)')
        if not name:
            return
        from core.scene import Scene
        from core import project
        path = Path(name).with_suffix('.igzproj')
        try:
            project.create(Scene(), path)
            self.window_host.open_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Project', str(exc))
            return
        self.accept()

    def open_dialog(self):
        name, _ = file_dialogs.getOpenFileName(self, 'Open', '', 'IngeTrazo (*.igz *.igzproj)')
        if name:
            self.open_recent(name)
