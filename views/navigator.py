# SPDX-License-Identifier: GPL-3.0-or-later
"""Experimental faceted navigation beside the existing specialist panels.

Results are paged and placement children are created only on expansion; a large
model must not allocate ninety thousand Qt items just to open this dock.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem, QSplitter,
    QInputDialog, QMessageBox, QMenu, QFileDialog, QAbstractItemView)
from core import facets, bim_registry
from core.agent_facets import FacetTools, set_display, previous_display
from core.history import AssignLayerCommand, SetRecordCommand, CompoundCommand, SetRegistryCommand


class NavigatorDock(QDockWidget, FacetTools):
    def __init__(self, window):
        super().__init__('Navigator', window)
        self.setObjectName('NavigatorDock')
        self._window = window
        self.checked = {}
        self._base_filter = None
        self.current_filter = None
        self._busy = False
        self._signature = None
        self._selection = None
        self.index = None
        self.result_uids = []
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name or path (glob)')
        layout.addWidget(self.search)
        row = QHBoxLayout()
        self.views = QComboBox()
        row.addWidget(self.views)
        layout.addLayout(row)
        self.button(row, 'Save view…', self.save_view)
        self.button(row, 'Previous view', self.previous_view)
        self.color = QComboBox()
        self.color.addItem('Colour by…', None)
        layout.addWidget(self.color)
        for actions in [ [('Select all results', self.select_all), ('Isolate', self.isolate),
                           ('Hide results', self.hide_results), ('Show all', self.show_all)],
                         [('Classify…', self.classify), ('Tag…', self.tag), ('Rule…', self.rule), ('Export…', self.export)]]:
            row = QHBoxLayout()
            layout.addLayout(row)
            for title, callback in actions:
                self.button(row, title, callback)
        split = QSplitter()
        layout.addWidget(split)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Facet / value', 'Count'])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(['Name', 'Class', 'Kinds', 'Tag', 'Storey'])
        self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        split.addWidget(self.tree)
        split.addWidget(self.results)
        self.status = QPushButton('More results…')
        layout.addWidget(self.status)
        self.status.clicked.connect(self.more_results)
        self.tree.itemChanged.connect(self.changed)
        self.results.itemExpanded.connect(self.expand)
        self.results.itemSelectionChanged.connect(self.select_rows)
        self.search.textChanged.connect(self.schedule)
        self.views.activated.connect(self.apply_saved)
        self.color.activated.connect(self.isolate)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.refilter)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()
        self.visibilityChanged.connect(lambda visible: self.refresh() if visible else None)

    @property
    def _viewport(self):
        return self._window.viewport

    def button(self, row, text, callback):
        button = QPushButton(text)
        button.clicked.connect(lambda: self.guard(callback))
        row.addWidget(button)

    def guard(self, callback):
        try:
            callback()
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'Navigator', str(exc))

    def schedule(self):
        if not self._busy:
            self.debounce.start()

    def refresh(self):
        if not self.isVisible():
            return
        scene = self._viewport.scene
        signature = (id(scene), getattr(scene, 'content_version', scene.version), len(scene.groups))
        if signature != self._signature:
            self._signature = signature
            self.index = facets.build(scene)
            self._busy = True
            self.views.clear()
            self.views.addItem('Saved views…', None)
            for key, view in bim_registry.get(scene).get('views', {}).items():
                self.views.addItem(view['name'], key)
            color = self.color.currentData()
            self.color.clear()
            self.color.addItem('Colour by…', None)
            for name in self.facet_names():
                self.color.addItem(name, name)
            self.color.setCurrentIndex(max(0, self.color.findData(color)))
            self._busy = False
            self.refilter()
        selection = frozenset(id(g) for g in scene.selection)
        if selection != self._selection:
            self._selection = selection
            self._busy = True
            for i in range(self.results.topLevelItemCount()):
                parent = self.results.topLevelItem(i)
                parent.setSelected(any(id(self.index.groups[u]) in selection for u in parent.data(0, Qt.UserRole)))
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    uid = child.data(0, Qt.UserRole)
                    child.setSelected(isinstance(uid, str) and uid in self.index.groups and id(self.index.groups[uid]) in selection)
            self._busy = False

    def facet_names(self):
        kinds = sorted({k for row in self.index.values() for k in row if k.startswith('kind:')})
        return ['class', *kinds, 'system', 'storey', 'tag', 'definition', 'type', 'material', 'status', 'linked', 'path']

    def expression(self, exclude=None):
        clauses = [self._base_filter] if self._base_filter is not None else []
        for name, values in self.checked.items():
            if not values or name == exclude:
                continue
            choices = [{'facet': name, 'in': [v for v in values if v is not None]}]
            if None in values:
                choices.append({'facet': name, 'exists': False})
            clauses.append({'any': choices})
        text = self.search.text().strip()
        if text:
            clauses.append({'text': text if any(c in text for c in '*?[') else '*' + text + '*'})
        return {'all': clauses}

    def refilter(self):
        if self.index is None:
            return
        self.current_filter = self.expression()
        self.result_uids = facets.evaluate(self.index, self.current_filter)
        self._busy = True
        self.tree.clear()
        for name in self.facet_names():
            parent = QTreeWidgetItem(self.tree, [name])
            # Material fallback is opt-in, since it may materialize deferred meshes.
            if name == 'material' and 'material' not in self.index.lazy:
                button = QPushButton('Compute face materials…')
                child = QTreeWidgetItem(parent)
                self.tree.setItemWidget(child, 0, button)
                button.clicked.connect(self.compute_materials)
                continue
            count_uids = self.result_uids
            if self.checked.get(name):
                count_uids = facets.evaluate(self.index, self.expression(exclude=name))
            counts = facets.values(self.index, name, count_uids)
            missing = sum(self.index[u].get(name) in (None, '', []) for u in count_uids)
            if missing:
                counts[None] = missing
            choices = sorted(counts, key=lambda v: (-counts[v], str(v)))
            choices = list(dict.fromkeys(list(self.checked.get(name, ())) + choices))
            self.fill_values(parent, name, counts, choices[:50])
            if len(choices) > 50:
                child = QTreeWidgetItem(parent)
                box = QLineEdit()
                box.setPlaceholderText('More… filter values')
                self.tree.setItemWidget(child, 0, box)
                box.textChanged.connect(lambda text, p=parent, n=name, c=counts, vs=choices: self.more_values(p, n, c, vs, text))
            parent.setExpanded(bool(self.checked.get(name)))
        self.results.clear()
        self._result_offset = 0
        self.more_results()
        self._busy = False

    def fill_values(self, parent, name, counts, choices):
        for value in choices:
            item = QTreeWidgetItem(parent, ['(missing)' if value is None else str(value), str(counts.get(value, 0))])
            item.setData(0, Qt.UserRole, (name, value))
            item.setCheckState(0, Qt.Checked if value in self.checked.get(name, ()) else Qt.Unchecked)

    def more_values(self, parent, name, counts, choices, text):
        self._busy = True
        for i in reversed(range(parent.childCount())):
            if parent.child(i).data(0, Qt.UserRole) is not None:
                parent.takeChild(i)
        self.fill_values(parent, name, counts, [v for v in choices if text.casefold() in str(v).casefold()][:50])
        self._busy = False

    def compute_materials(self):
        self.index.prepare('material')
        self.refilter()

    def changed(self, item):
        data = item.data(0, Qt.UserRole)
        if self._busy or data is None:
            return
        name, value = data
        choices = self.checked.setdefault(name, set())
        if item.checkState(0) == Qt.Checked:
            choices.add(value)
        else:
            choices.discard(value)
        self.schedule()

    def more_results(self):
        if self._result_offset == 0:
            grouped = {}
            for uid in self.result_uids:
                grouped.setdefault(self.index[uid]['definition'], []).append(uid)
            self._definition_results = list(grouped.items())
        for name, uids in self._definition_results[self._result_offset:self._result_offset + 1000]:
            item = QTreeWidgetItem(self.results, [f'{name} ({len(uids)})'])
            item.setData(0, Qt.UserRole, uids)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self._result_offset += 1000
        self.status.setText(f'{len(self.result_uids)} results — More…')
        self.status.setEnabled(self._result_offset < len(self._definition_results))

    def expand(self, item):
        if item.childCount():
            return
        uids = item.data(0, Qt.UserRole) or []
        for uid in uids[:500]:
            row = self.index[uid]
            kinds = ', '.join(str(v) for k, vs in row.items() if k.startswith('kind:') for v in vs)
            child = QTreeWidgetItem(item, [str(row['name'] or ''), str(row['class'] or ''), kinds,
                                          str(row['tag'] or ''), str(row['storey'] or '')])
            child.setData(0, Qt.UserRole, uid)
        if len(uids) > 500:
            more = QTreeWidgetItem(item, [f'More placements… ({len(uids) - 500})'])
            more.setData(0, Qt.UserRole, uids[500:])
            more.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)

    def select_rows(self):
        if self._busy:
            return
        uids = []
        for item in self.results.selectedItems():
            data = item.data(0, Qt.UserRole)
            uids.extend(data if isinstance(data, list) else [data])
        if not uids:
            self._viewport.scene.clear_selection()
            self._viewport.update()
            return
        # The viewport edits one containment context, just like the Outliner.
        # Metadata toolbar actions still target the entire result set directly.
        from views.outliner import open_to
        path = self.index[uids[0]]['path_uids']
        if not open_to(self._viewport, [self.index.groups[u] for u in path]):
            return
        scene = self._viewport.scene
        siblings = [self.index.groups[u] for u in uids
                    if self.index[u]['path_uids'] == path
                    and scene.entity_selectable(self.index.groups[u])]
        scene.select(siblings)
        self._viewport.update()

    def select_all(self):
        self._viewport.scene.select([self.index.groups[u] for u in self.result_uids])
        self._viewport.update()

    def isolate(self):
        set_display(self._viewport, self.current_filter, self.color.currentData())

    def hide_results(self):
        # Complement only maximal subtree roots would leak unmatched ancestors.
        # Use the exact complement as display membership instead.
        set_display(self._viewport, {'not': self.current_filter}, self.color.currentData(), exact=True)

    def show_all(self):
        set_display(self._viewport)
        self.sync_filter_controls()

    def previous_view(self):
        if not getattr(self._viewport, '_previous_views', []):
            return
        previous_display(self._viewport)
        self.sync_filter_controls()

    def sync_filter_controls(self):
        """A restored display must show the same scope in the result list."""
        self._busy = True
        self._base_filter = getattr(self._viewport, '_view_expression', None)
        self.checked.clear()
        self.search.clear()
        self.color.setCurrentIndex(max(0, self.color.findData(getattr(self._viewport, '_view_color', None))))
        self.views.setCurrentIndex(max(0, self.views.findData(getattr(self._viewport, 'active_view_key', None))))
        self._busy = False
        self.refilter()

    def save_view(self):
        key, ok = QInputDialog.getText(self, 'Save view', 'View key / name')
        if ok and key:
            self._tool_save_view(key, key, self.current_filter, self.color.currentData(), True)

    def apply_saved(self):
        key = self.views.currentData()
        if key:
            view = bim_registry.get(self._viewport.scene)['views'][key]
            self._busy = True
            self._base_filter = view['filter']
            self.checked.clear()
            self.search.clear()
            self.color.setCurrentIndex(max(0, self.color.findData(view.get('color_by'))))
            self._busy = False
            self.refilter()
            self._tool_apply_view(key)

    def targets(self, selected=False):
        uids = [u for u, g in self.index.groups.items() if g in self._viewport.scene.selection] if selected else self.result_uids
        if any(self.index[u]['linked'] for u in uids):
            raise ValueError('Linked groups must be edited in their source file')
        return [self.index.groups[u] for u in uids]

    def record_patch(self):
        from views.object_record import RecordDialog
        targets = self.targets()
        if not targets:
            return None
        dialog = RecordDialog(self, targets[0].ifc, bim_registry.get(self._viewport.scene))
        return dialog.patch if dialog.exec() else None

    def classify(self):
        patch = self.record_patch()
        if patch is not None:
            self._viewport.history.execute(SetRecordCommand(self.targets(), patch))
            self._viewport.refresh_after_edit()

    def tag(self):
        name, ok = QInputDialog.getItem(self, 'Tag results', 'Tag', [l.name for l in self._viewport.scene.layers], 0, False)
        if ok:
            self._viewport.history.execute(AssignLayerCommand(self.targets(), name))
            self._viewport.refresh_after_edit()

    def rule(self):
        patch = self.record_patch()
        if patch is None:
            return
        key, ok = QInputDialog.getText(self, 'Rule', 'Rule key / name (save and apply now)')
        if ok and key:
            self._tool_set_rule(key, dict(name=key, filter=self.current_filter, apply=dict(patch=patch)))
            self._tool_apply_rule(key)

    def context(self, point):
        item = self.tree.itemAt(point)
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return
        name, value = data
        if value is None:
            return
        if name not in ('class', 'system', 'type', 'status', 'tag', 'storey') and not name.startswith('kind:'):
            return
        menu = QMenu(self)
        action = menu.addAction('Apply to selection')
        if menu.exec(self.tree.mapToGlobal(point)) == action:
            self.guard(lambda: self.apply_value(name, value))

    def apply_value(self, name, value):
        groups = self.targets(selected=True)
        commands = []
        for group in groups:
            rec = group.ifc or {}
            if name == 'tag':
                commands.append(AssignLayerCommand([group], value))
                continue
            patch = {name: value}
            if name.startswith('kind:'):
                system = name[5:]
                items = [c for c in rec.get('classifications', []) if (c['system'], c['code']) != (system, value)]
                patch = {'classifications': items + [dict(system=system, code=value, name=value)]}
            elif name == 'system':
                patch = {'systems': list(dict.fromkeys(rec.get('systems', []) + [value]))}
            elif name == 'status':
                from copy import deepcopy
                psets = deepcopy(rec.get('psets', {}))
                psets.setdefault('Pset_' + rec.get('class', 'IfcBuildingElementProxy')[3:] + 'Common', {})['Status'] = value
                patch = {'psets': psets}
            commands.append(SetRecordCommand([group], patch))
        if commands:
            self._viewport.history.execute(CompoundCommand(commands))
            self._viewport.refresh_after_edit()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export current results', '', 'IFC (*.ifc)')
        if path:
            from formats.ifc import save_ifc
            registry = bim_registry.get(self._viewport.scene)
            registry.setdefault('export_profiles', {})['navigator'] = dict(schema='IFC4', filter=self.current_filter)
            self._viewport.history.execute(SetRegistryCommand(registry))
            save_ifc(self._viewport.scene, path, profile='navigator')
