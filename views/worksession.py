# SPDX-License-Identifier: GPL-3.0-or-later
"""Window orchestration separates the viewed tab from the editable project file.

The ordinary document tabs stay usable outside a worksession. Project state is
merged on save/close, so it never replaces another host's shared registry.
"""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMessageBox
from core import project, recent
from formats import project as storage


class WorksessionMixin:
    _session_path = None
    _active_file = None
    _opening_session = False
    _session_unsaved_doc = None

    def show_home(self):
        from views.home import Home
        self._home = Home(self)
        self._home.show()
        self._home.raise_()

    def _dismiss_home(self):
        home = getattr(self, '_home', None)
        if home is not None:
            home.hide()

    def query_worksession(self):
        roles = {}
        if self._session_path:
            value = storage.load(self._session_path)
            roles = {str((self._session_path.parent / r['path']).resolve()): r['role']
                     for r in value['files']}
        return dict(project=str(self._session_path) if self._session_path else None,
                    active_file=self._active_file,
                    files=[dict(path=str(d.path.resolve()),
                                role=roles.get(str(d.path.resolve()), 'host'),
                                read_only=getattr(d, 'read_only', False))
                           for d in self.documents() if d.path])

    def persist_worksession(self):
        if self._session_path and not self._opening_session:
            rows = [dict(path=str(d.path), camera=self._camera_dict(d.viewport))
                    for d in self.documents() if d.path]
            paths = {str(Path(r['path']).resolve()) for r in rows}
            if self._active_file not in paths and self._session_unsaved_doc not in self.documents():
                self._active_file = next((str(d.path.resolve()) for d in self.documents() if d.path), None)
            project.save_worksession(self._session_path, rows, self._active_file)

    def open_project(self, path):
        path = Path(path).resolve()
        state = project.worksession(path)
        # Validate all sources before changing the currently open session.
        for row in state['files']:
            if not Path(row['path']).is_file():
                raise FileNotFoundError(row['path'])
        self.persist_worksession()
        self._session_path = path
        self._opening_session = True
        try:
            for row in state['files']:
                if not self.open_path(Path(row['path'])):
                    raise ValueError('Could not open ' + row['path'])
                self._apply_camera_dict(row.get('camera'))
            # Restore order even when some of these documents were already open.
            bar = self._project_tabs
            for index, row in enumerate(state['files']):
                doc = next(d for d in self.documents() if d.same_file(row['path']))
                bar.tabs.moveTab(bar.index_of(doc), index)
            self._active_file = state['active_file']
            self._session_unsaved_doc = self._doc if not self._active_file else None
            if self._active_file:
                self.set_active_file(self._active_file)
            self._refresh_worksession()
            recent.remember(path)
            self._dismiss_home()
        finally:
            self._opening_session = False
        return True

    def set_active_file(self, path):
        path = Path(path).resolve()
        if not self._session_path:
            raise ValueError('Open a project first')
        value = storage.load(self._session_path)
        allowed = {(self._session_path.parent / e['path']).resolve()
                   for e in value['files'] if e['role'] in ('host', 'linked')}
        allowed.update(d.path.resolve() for d in self.documents() if d.path)
        if path not in allowed or path.suffix.lower() != '.igz':
            raise ValueError('Active file must be a project document')
        if not self.open_path(path):
            raise ValueError('Could not open active file')
        self._active_file = str(path)
        self._session_unsaved_doc = None
        self._refresh_worksession()
        self.persist_worksession()
        return self.query_worksession()

    def _refresh_worksession(self):
        if not self._session_path:
            return
        for doc in self.documents():
            doc.read_only = (not doc.same_file(self._active_file) if self._active_file
                             else doc is not self._session_unsaved_doc)
            doc.viewport.scene.worksession_read_only = doc.read_only
            # Disable direct tool gestures as well as history commands. Tab
            # selection and the project browser remain available.
            doc.viewport.setEnabled(not doc.read_only)
            doc.slot_widget().setEnabled(not doc.read_only)
            if doc.composer is not None:
                doc.composer.setEnabled(not doc.read_only)
            self._update_tab(doc)
        # Panels and menu commands can mutate outside History (units,
        # imports, styles). Keep only file navigation and the session picker
        # interactive while inspecting a non-active tab.
        from PySide6.QtWidgets import QDockWidget, QToolBar
        for widget, enabled in getattr(self, '_session_disabled', []):
            widget.setEnabled(enabled)
        self._session_disabled = []
        if getattr(self._doc, 'read_only', False):
            targets = list(self.findChildren(QToolBar))
            targets += [d for d in self.findChildren(QDockWidget)
                        if d is not self.project_browser]
            targets += [self.project_browser.outliner, self.project_browser.links_panel]
            menus = self.menuBar().actions()
            targets += menus[1:]
            from core.i18n import tr
            allowed = {tr('Home'), tr('New'), tr('New Window'), tr('Open…'),
                       tr('Save'), tr('Save As…'), tr('Exit')}
            if menus and menus[0].menu():
                targets += [a for a in menus[0].menu().actions()
                            if a.text().replace('&', '') not in allowed]
            for widget in targets:
                self._session_disabled.append((widget, widget.isEnabled()))
                widget.setEnabled(False)
        listing = getattr(self, '_worksession_list', None)
        if listing is None:
            listing = self._worksession_list = QListWidget()
            from PySide6.QtWidgets import QTabWidget
            tabs = self.project_browser.findChild(QTabWidget)
            if tabs is not None:
                tabs.addTab(listing, 'Worksession')
            listing.itemClicked.connect(self._choose_active_item)
        listing.clear()
        value = storage.load(self._session_path)
        rows = {str((self._session_path.parent / r['path']).resolve()): r['role']
                for r in value['files']}
        for doc in self.documents():
            if doc.path:
                rows.setdefault(str(doc.path.resolve()), 'host')
        for path, role in rows.items():
            item = QListWidgetItem(('● ' if path == self._active_file else '') +
                                   Path(path).name + ' — ' + role)
            item.setData(Qt.UserRole, path)
            if role == 'reference':
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            listing.addItem(item)

    def _choose_active_item(self, item):
        try:
            self.set_active_file(item.data(Qt.UserRole))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Active file', str(exc))
