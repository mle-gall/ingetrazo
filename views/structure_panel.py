# SPDX-License-Identifier: GPL-3.0-or-later
"""Maxence, 2026-11-10: file placements here so their records and tags agree."""
from collections import Counter, defaultdict

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QDockWidget,
    QHeaderView, QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core import bim_registry, links, outliner, structure
from core.agent_facets import previous_display, set_display
from core.group import Group, new_uid
from core.history import CompoundCommand, SetRegistryCommand
from core.i18n import tr
from views.composer import SCENE_MIME
from views.panel_refresh import refresh_steps
from views.structure_recipe import RecipeDialog, execute, update_node

PLACEMENT_MIME = 'application/x-ingetrazo-placement-uids'
NODE = Qt.UserRole
UID = Qt.UserRole + 1
PAGE = 200


def pick_node(parent, registry):
    nodes = structure._nodes(registry)
    keys = [key for key in nodes if 'source' not in nodes[key]]
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(tr("Re-file under…"))
    dialog.setLabelText(tr("Structure"))
    if not keys:
        return None
    dialog.setComboBoxItems([' › '.join(structure.path(registry, key)) for key in keys])
    from PySide6.QtWidgets import QComboBox
    if dialog.exec():
        return keys[dialog.findChild(QComboBox).currentIndex()]
    return None


class FilingTree(QTreeWidget):
    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setUniformRowHeights(True)

    def mimeData(self, items):
        data = QMimeData()
        uids = [uid for item in items if (uid := item.data(0, UID))]
        if uids:
            data.setData(PLACEMENT_MIME, '\n'.join(uids).encode())
        return data

    def dragEnterEvent(self, event):
        source = event.source()
        local = source is None or source.window() in (self.window(), self.dock.parent())
        if local and any(event.mimeData().hasFormat(t) for t in (SCENE_MIME, PLACEMENT_MIME)):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(0, NODE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(0, NODE) and self.dock.file_drop(event.mimeData(), item.data(0, NODE)):
            event.acceptProposedAction()
        else:
            event.ignore()


class BootstrapDialog(QDialog):
    def __init__(self, parent, viewport):
        super().__init__(parent)
        self.setWindowTitle(tr("Propose structure from tags…"))
        self.viewport = viewport
        self.proposal = proposal = structure.bootstrap(viewport.scene, bim_registry.get(viewport.scene))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("{nodes} nodes · {filings} filings", nodes=len(proposal['structure']['nodes']),
                                   filings=sum(map(len, proposal['filing'].values())))))
        layout.addWidget(QLabel(tr("Conflicts")))
        conflicts = QPlainTextEdit()
        conflicts.setReadOnly(True)
        conflicts.setPlainText('\n'.join(f"{c.get('name') or c.get('node') or c.get('uid', '')} — "
                                         f"{tr(c['reason'])} {c.get('message', c.get('count', ''))}"
                                         for c in proposal['conflicts']))
        layout.addWidget(conflicts)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)

    def submit(self):
        try:
            execute(self.viewport, structure.apply_bootstrap(self.viewport.scene, self.proposal))
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class StructureDock(QDockWidget):
    def __init__(self, window):
        super().__init__(tr("Structure"), window)
        self.setObjectName('StructureDock')
        self.window_owner = window
        self.items = {}
        self._signature = self._building = self._pending_refresh = None
        self._front = False
        body = QWidget()
        layout = QVBoxLayout(body)
        self.file_button = QPushButton(tr("File selection here"))
        self.file_button.setEnabled(False)
        self.file_button.clicked.connect(self.file_selection)
        layout.addWidget(self.file_button)
        self.tree = FilingTree(self)
        self.tree.setHeaderLabels([tr("Name"), tr("Members"), tr("Problems")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        self.tree.currentItemChanged.connect(lambda item, _: self.file_button.setEnabled(
            bool(item and item.data(0, NODE))))
        self.tree.itemSelectionChanged.connect(self.select_unsorted)
        self.tree.itemClicked.connect(self.clicked)
        self.tree.itemDoubleClicked.connect(self.double_clicked)
        self.tree.itemExpanded.connect(self.expanded)
        layout.addWidget(self.tree)
        propose = QPushButton(tr("Propose structure from tags…"))
        propose.clicked.connect(self.propose)
        layout.addWidget(propose)
        self.setWidget(body)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        # Bridge edits may bump the document without painting the hidden GL
        # widget on Metal. Check only the cheap token while this tab is front.
        self.watch = QTimer(self)
        self.watch.setInterval(500)
        self.watch.timeout.connect(self.on_scene_changed)
        self.visibilityChanged.connect(self.visibility)
        if hasattr(window, 'documentChanged'):
            window.documentChanged.connect(self.document_changed)

    @property
    def vp(self):
        return self.window_owner.viewport

    def document_changed(self):
        # A closed ride must not be kept alive by a background tab's row cache.
        if self._signature and self._signature[0] is not self.vp.scene:
            self._signature = self._building = self._pending_refresh = None
            self.direct, self.unsorted, self.page_groups = {}, [], {}
        self.on_scene_changed()

    def visibility(self, visible):
        self._front = visible
        if visible:
            self.watch.start()
            self.on_scene_changed()
        else:
            self.watch.stop()
            self.timer.stop()
            self._pending_refresh = self._building = None

    def on_scene_changed(self):
        if self._front and self.isVisible():
            scene = self.vp.scene
            if self._signature != (scene, scene.content_version):
                self.tree.setEnabled(False)
                self.file_button.setEnabled(False)
                if not self.timer.isActive():
                    self.timer.start(80)

    def refresh(self):
        if not self._front or not self.isVisible():
            return
        scene = self.vp.scene
        signature = (scene, scene.content_version)
        if signature in (self._signature, self._building):
            return
        self._building = signature

        def current():
            return self._front and self.vp.scene is scene and scene.content_version == signature[1]

        refresh_steps(self, self._build(scene, signature), deferred=True, current=current)

    def _build(self, scene, signature):
        registry = bim_registry.get(scene)
        nodes = structure._nodes(registry)
        recipes = {key: structure.resolve(registry, key) for key in nodes}
        children = structure.tree(registry)
        direct, counts, problems = defaultdict(list), Counter(), Counter()
        unsorted = []
        for i, (g, source, root, key) in enumerate(structure._memberships(scene, registry)):
            review = structure._is_unsorted(g, source, root, key, recipes)
            if review:
                unsorted.append(g)
            if key in nodes:
                direct[key].append(g)
                counts[key] += 1
                # A class-less node (fasteners, reference) expects no record:
                # only nodes that promise a class count a missing Status.
                expects_record = recipes[key].get('class') is not None
                problems[key] += int(expects_record and not structure._has_status(g.ifc or {})) + int(review)
            if i % 128 == 127:
                yield
        order, stack = [], list(reversed(children[None]))
        while stack:
            key = stack.pop()
            order.append(key)
            stack.extend(reversed(children[key]))
        for key in reversed(order):
            parent = nodes[key]['parent']
            counts[parent] += counts[key]
            problems[parent] += problems[key]
        same_scene = self._signature and signature[0] is self._signature[0]
        expanded = {k for k, item in self.items.items() if same_scene and item.isExpanded()}
        current = self.tree.currentItem()
        current_key = current.data(0, NODE) if same_scene and current else None
        review_open = same_scene and self.review.isExpanded()
        active = registry.get('structure', {}).get('active')
        self.tree.clear()
        self.items = {}
        self.children, self.direct, self.unsorted = children, direct, unsorted
        for key in order:
            node = nodes[key]
            name = node['name']
            if 'source' in node:
                stem = links.stem(node['source'])
                name = f"↗ {stem}" if name == stem else f"{name} ↗ {stem}"
            parent = self.items.get(node['parent'], self.tree)
            item = QTreeWidgetItem(parent, [name, str(counts[key]), str(problems[key]) if problems[key] else ''])
            item.setData(0, NODE, key)
            item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
            font = item.font(0)
            font.setBold(key == active)
            font.setItalic('source' in node)
            item.setFont(0, font)
            self.items[key] = item
            item.setExpanded(key in expanded or (not same_scene and not node['parent']))
        self.review = QTreeWidgetItem(self.tree, [tr("Unsorted"), str(len(unsorted))])
        self.review.setFlags(self.review.flags() & ~Qt.ItemIsDragEnabled)
        self.more = None
        self.page_groups = {}
        if unsorted:
            self.review.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        if review_open:
            self.review.setExpanded(True)
        if current_key in self.items:
            self.tree.setCurrentItem(self.items[current_key])
        self.tree.setEnabled(True)
        self._signature, self._building = signature, None

    def expanded(self, item):
        if item is getattr(self, 'review', None) and not item.childCount():
            self.next_page()

    def next_page(self):
        if self.more:
            self.review.takeChild(self.review.indexOfChild(self.more))
            self.more = None
        start = self.review.childCount()
        for g in self.unsorted[start:start + PAGE]:
            label = ' · '.join(filter(None, (g.name, (g.ifc or {}).get('class'))))
            item = QTreeWidgetItem(self.review, [label])
            self.page_groups[g.uid] = g
            item.setData(0, UID, g.uid)
        if start + PAGE < len(self.unsorted):
            self.more = QTreeWidgetItem(self.review, [tr("More…")])

    def groups(self, key):
        stack = [key]
        while stack:
            k = stack.pop()
            yield from self.direct[k]
            stack.extend(reversed(self.children[k]))

    def select_unsorted(self):
        if self._building is not None:
            return
        groups = [self.page_groups[uid] for row in self.tree.selectedItems() if (uid := row.data(0, UID))]
        if groups and set(groups) != self.vp.scene.selection:
            self.select_groups(groups)

    def clicked(self, item, column):
        if item is self.more:
            self.next_page()
            return
        key = item.data(0, NODE)
        if key:
            self.select_groups(list(self.groups(key)))
        elif item.data(0, UID):
            self.select_unsorted()

    def select_groups(self, groups):
        from views.outliner import open_to
        scene = self.vp.scene
        path = []
        if groups:
            parents = outliner.parents(scene.groups)
            p = parents.get(id(groups[0]))
            if all(parents.get(id(g)) is p for g in groups):
                while p is not None and not links.is_linked(p):
                    path.append(p)
                    p = parents.get(id(p))
                path = [] if p else list(reversed(path))
        if open_to(self.vp, path):
            scene.select(g for g in groups if scene.entity_selectable(g))
            getattr(self.vp, "notify_scene_changed", self.vp.update)()

    def double_clicked(self, item, column):
        if key := item.data(0, NODE):
            self.guard(lambda: self.display(key))

    def display(self, key, hide=False):
        expr = {'facet': 'uid', 'in': [g.uid for g in self.groups(key)]}
        set_display(self.vp, {'not': expr} if hide else expr, isolate=True, exact=True)

    def show_all(self):
        if getattr(self.vp, '_previous_views', []):
            previous_display(self.vp)
        else:
            set_display(self.vp, remember=False)

    def guard(self, action):
        try:
            action()
            return True
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, tr("Structure"), str(exc))
            return False

    def file_selection(self):
        item = self.tree.currentItem()
        key = item.data(0, NODE) if item else None
        if key:
            self.guard(lambda: self.file_selected_groups(key))

    def file_selected_groups(self, key):
        uids = [g.uid for g in self.vp.scene.selection if isinstance(g, Group)]
        self.file_uids(uids, key)

    def file_uids(self, uids, key):
        execute(self.vp, structure.file(self.vp.scene, uids, key))

    def file_drop(self, data, key):
        def apply():
            if data.hasFormat(PLACEMENT_MIME):
                uids = bytes(data.data(PLACEMENT_MIME)).decode().splitlines()
            else:
                names = set(bytes(data.data(SCENE_MIME)).decode().splitlines())
                matches, linked = defaultdict(list), defaultdict(list)
                for g, src, _ in structure._placements(self.vp.scene):
                    if g.name in names:
                        (linked if src else matches)[g.name].append(g.uid)
                # A linked-only match goes through file() for its precise refusal.
                for name in names - matches.keys():
                    matches[name] = linked[name]
                if any(len(matches[n]) != 1 for n in names):
                    raise ValueError(tr("A group name is missing or ambiguous"))
                uids = [matches[n][0] for n in names]
            self.file_uids(uids, key)
        return self.guard(apply)

    def propose(self):
        scene = self.vp.scene
        if structure._nodes(bim_registry.get(scene)):
            if QMessageBox.question(self, tr("Structure"), tr("Replace the existing structure?")) != QMessageBox.Yes:
                return
        BootstrapDialog(self, self.vp).exec()

    def context(self, pos):
        item = self.tree.itemAt(pos)
        key = item.data(0, NODE) if item else None
        registry = bim_registry.get(self.vp.scene)
        nodes = structure._nodes(registry)
        if key and key not in nodes:
            return
        menu = QMenu(self)
        def add(label, action):
            menu.addAction(label, lambda: self.guard(action))
        if key:
            add(tr("Isolate"), lambda: self.display(key))
            add(tr("Hide members"), lambda: self.display(key, hide=True))
        add(tr("Show all"), self.show_all)
        add(tr("Colour by node"), lambda: set_display(
            self.vp, getattr(self.vp, '_view_expression', None), 'structure',
            isolate=getattr(self.vp, '_view_isolate', True), exact=getattr(self.vp, '_view_exact', False)))
        if key and 'source' not in nodes[key]:
            add(tr("File selection here"), lambda: self.file_selected_groups(key))
            add(tr("Set as active node"), lambda: self.set_active(key))
            add(tr("Rename"), lambda: self.rename(key, nodes[key]['name']))
            add(tr("Edit recipe…"), lambda: RecipeDialog(self, self.vp, key).exec())
            add(tr("Delete node"), lambda: self.delete(key))
        if not key or 'source' not in nodes[key]:
            add(tr("New child node…") if key else tr("New node…"), lambda: self.new_node(key))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def set_active(self, key):
        registry = bim_registry.get(self.vp.scene)
        registry['structure']['active'] = key
        execute(self.vp, SetRegistryCommand(registry))

    def rename(self, key, old):
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("Name"), text=old)
        if ok:
            update_node(self.vp, key, name=name.strip())

    def new_node(self, parent):
        name, ok = QInputDialog.getText(self, tr("New node…"), tr("Name"))
        if ok:
            registry = bim_registry.get(self.vp.scene)
            nodes = registry.setdefault('structure', {}).setdefault('nodes', {})
            order = max((n['order'] for n in nodes.values() if n['parent'] == parent), default=-1) + 1
            nodes[new_uid()] = dict(name=name.strip(), parent=parent, order=order)
            execute(self.vp, SetRegistryCommand(registry))

    def delete(self, key):
        scene = self.vp.scene
        registry = bim_registry.get(scene)
        section = registry['structure']
        if structure.tree(registry)[key]:
            raise ValueError(tr("Remove child nodes first"))
        parent = section['nodes'][key]['parent']
        uids = structure.members(scene, key)
        commands = []
        if uids:
            if not parent:
                raise ValueError(tr("Re-file members before deleting this node"))
            if QMessageBox.question(self, tr("Delete node"), tr("Re-file members to parent?")) != QMessageBox.Yes:
                return
            commands.append(structure.file(scene, uids, parent))
        del section['nodes'][key]
        if section.get('active') == key:
            section.pop('active')
        commands.insert(0, SetRegistryCommand(registry, refiled_uids=uids))
        execute(self.vp, CompoundCommand(commands))
