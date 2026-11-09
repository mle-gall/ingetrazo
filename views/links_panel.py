# SPDX-License-Identifier: GPL-3.0-or-later
"""A live view of references, with subset edits scoped to one placement."""
import json
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QTreeWidget,
                               QTreeWidgetItem, QPushButton, QInputDialog,
                               QFileDialog, QMessageBox, QSizePolicy)
from core import links, project


class LinksPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Source', 'Status', 'Subset', 'Stable UIDs'])
        # The tree takes what the buttons leave and asks for no minimum of
        # its own, so the tab stays as short as the Model tab.
        self.tree.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.tree)
        # Two columns: eight buttons one under the other gave this tab a
        # minimum height that outgrew the Model tab's and, while the trays
        # are docked one under the other before being tabbed, the window's.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        layout.addLayout(grid)
        actions = [('Refresh', self.refresh), ('Link selection…', self.link_selection),
                   ('Edit linked subset', self.edit_subset), ('Reload', self.reload),
                   ('Relink…', self.relink), ('Open source', self.open_source),
                   ('Pack / unpack', self.pack), ('Move registry to project…', self.move_registry)]
        for i, (label, action) in enumerate(actions):
            button = QPushButton(label)
            # Two long labels side by side must not set the side tray's
            # minimum width (the window's floor grew past the sheet tabs'
            # test): the buttons take the width they get, elided by Qt.
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, fn=action: self.run(fn))
            grid.addWidget(button, i // 2, i % 2)

    @property
    def scene(self):
        return self.window.viewport.scene

    def run(self, action):
        try:
            action()
        except (ValueError, OSError, links.LinkError) as exc:
            QMessageBox.warning(self, 'Linked files', str(exc))

    def refresh(self):
        self.tree.clear()
        self.rows = links.query(self.scene)
        for row in self.rows:
            subset = row['select']
            summary = 'Full document' if subset is None else (
                str(len(subset['uids'])) + ' UIDs' if 'uids' in subset else 'Navigator filter')
            self.tree.addTopLevelItem(QTreeWidgetItem([
                row['path'], row['status'], summary, str(row['stable_uid_count'])]))

    def selected(self):
        item = self.tree.currentItem()
        if item is None:
            raise ValueError('Select a linked placement first')
        row = self.rows[self.tree.indexOfTopLevelItem(item)]
        group = next(g for g in links.linked_groups(self.scene) if g.uid == row['uid'])
        return group, links.link_of(group)

    def changed(self):
        self.window._relink_done('Linked files updated')
        self.refresh()

    def reload(self):
        _, rec = self.selected()
        links.reload(self.scene, rec['path'])
        self.changed()

    def open_source(self):
        _, rec = self.selected()
        self.window.open_path(Path(rec['path']))

    def pack(self):
        _, rec = self.selected()
        packed = not links.is_packed(self.scene, rec['path'])
        if not packed:
            links.reload(self.scene, rec['path'])
        links.set_packed(self.scene, rec['path'], packed)
        self.changed()

    def edit_subset(self):
        _, rec = self.selected()
        text, ok = QInputDialog.getMultiLineText(self, 'Edit linked subset',
            'JSON: null (full), {"uids":[…]} or {"filter":{…}}',
            json.dumps(rec.get('select'), indent=2))
        if not ok:
            return
        value = json.loads(text)
        links.validate_select(value)
        previous = dict(rec)
        rec['select'] = value
        try:
            links.reload(self.scene, rec['path'])
        except Exception:
            rec.clear()
            rec.update(previous)
            raise
        self.changed()

    def relink(self):
        _, rec = self.selected()
        path, _ = QFileDialog.getOpenFileName(self, 'Relink', '', 'IngeTrazo (*.igz)')
        if not path:
            return
        previous = dict(rec)
        rec.update(links._link_record(path, self.window._current_path))
        try:
            links.reload(self.scene, path)
        except Exception:
            rec.clear()
            rec.update(previous)
            raise
        self.changed()

    def link_selection(self):
        docs = [doc for doc in self.window.documents()
                if doc.path and doc.viewport.scene is not self.scene]
        names = [str(doc.path) for doc in docs]
        name, ok = QInputDialog.getItem(self, 'Link selection', 'Open source document', names, 0, False)
        if not ok:
            return
        doc = docs[names.index(name)]
        from core.group import Group
        uids = [g.uid for g in doc.viewport.scene.selection if isinstance(g, Group)]
        if not uids:
            raise ValueError('Select groups in the source document first and save it')
        self.window.link_igz_path(doc.path, select={'uids': uids})
        self.refresh()

    def move_registry(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Move registry to project', '', 'Project (*.igzproj)')
        if path:
            project.create(self.scene, path, self.window._current_path)
            self.changed()
