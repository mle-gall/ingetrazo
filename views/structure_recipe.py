# SPDX-License-Identifier: GPL-3.0-or-later
"""Maxence, 2026-11-10: edit local overrides without freezing inherited recipes."""
import json
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QWidget, QVBoxLayout)

from core import bim_registry, structure
from core.history import CompoundCommand, SetRegistryCommand
from core.i18n import tr
from core.ifc_tables import STATUS, TABLES, common_pset, predefined_types
from views.ifc_picker import ClassPicker
from views.object_record import ClassificationRows, SystemMembership


def execute(viewport, command):
    if isinstance(command, CompoundCommand) and not command.commands:
        return
    viewport.history.execute(command)
    error = viewport.history.last_error or viewport.history.last_rejected
    if error:
        raise ValueError(error)
    viewport.refresh_after_edit()


def update_node(viewport, key, **fields):
    registry = bim_registry.get(viewport.scene)
    node = registry['structure']['nodes'][key]
    if 'source' in node:
        raise ValueError(tr("Linked structure is read-only"))
    node.update(fields)
    update = SetRegistryCommand(registry)
    sync, _ = structure._resync(viewport.scene, registry, [key])
    execute(viewport, CompoundCommand([update, *sync.commands]))


class RecipeDialog(QDialog):
    def __init__(self, parent, viewport, key):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit recipe…"))
        self.viewport, self.key = viewport, key
        registry = self.registry = bim_registry.get(viewport.scene)
        node = registry['structure']['nodes'][key]
        recipe = self.original = node.get('recipe', {})
        parent_key = node['parent']
        self.inherited = structure.resolve(registry, parent_key) if parent_key else {}
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        form = QFormLayout(body)
        self.name = QLineEdit(node['name'])
        form.addRow(tr("Name"), self.name)
        self.cls = ClassPicker(registry)
        self.cls.insertItem(0, tr("Inherit"))
        self.cls.insertItem(1, tr("No IFC record"))
        if recipe.get('class'):
            self.cls.setCurrentText(recipe['class'])
        else:
            self.cls.setCurrentIndex(int('class' in recipe))
        form.addRow(tr("Class"), self.cls)
        self.predefined = QComboBox()
        form.addRow(tr("Predefined type"), self.predefined)
        self.object_type = QLineEdit(recipe.get('object_type', ''))
        form.addRow(tr("Object type"), self.object_type)
        self.cls.currentTextChanged.connect(self.update_enums)
        self.update_enums()
        if 'predefined_type' in recipe:
            self.predefined.setCurrentText(recipe['predefined_type'] or tr("None"))
        self.allowed = QListWidget()
        self.allowed.setSelectionMode(QAbstractItemView.MultiSelection)
        allowed = recipe.get('classes_allowed', [])
        for cls in dict.fromkeys(bim_registry.ordered_classes(registry) + sorted(TABLES)):
            item = QListWidgetItem(cls, self.allowed)
            item.setSelected(cls in allowed)
        form.addRow(tr("Allowed classes"), self.allowed)
        self.codes = ClassificationRows(recipe.get('classifications', []))
        self.codes.setHorizontalHeaderLabels([tr("System"), tr("Code"), tr("Name")])
        self.codes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        form.addRow(tr("Classifications"), self.codes)
        for label, func in [(tr("Add classification…"), self.add_code),
                            (tr("Remove"), self.codes.remove_selected)]:
            button = QPushButton(label)
            button.clicked.connect(func)
            form.addRow(button)
        self.systems = SystemMembership(recipe.get('systems', []), registry)
        form.addRow(tr("Systems"), self.systems)
        for widget in (self.allowed, self.codes, self.systems):
            widget.setMaximumHeight(82)
        self.type_box = QComboBox()
        self.type_box.addItems([tr("Inherit"), tr("None"), *registry.get('types', {})])
        if 'type' in recipe:
            self.type_box.setCurrentText(recipe['type'] or tr("None"))
        form.addRow(tr("Type"), self.type_box)
        self.status = QComboBox()
        self.status.addItems(['', *STATUS])
        self.old_pset = common_pset(self.effective_class() or '')
        status = recipe.get('psets', {}).get(self.old_pset, {}).get('Status', '')
        self.status.setCurrentText(status.get('value', '') if isinstance(status, dict) else status)
        form.addRow(tr("Status"), self.status)
        advanced = QPushButton(tr("Advanced"))
        advanced.setCheckable(True)
        form.addRow(advanced)
        overrides = QWidget()
        fields = QFormLayout(overrides)
        self.tag = QLineEdit(recipe.get('tag', ''))
        folder = recipe.get('folder', [])
        self.folder_text = folder if isinstance(folder, str) else ' / '.join(folder)
        self.folder = QLineEdit(self.folder_text)
        fields.addRow(tr("Tag"), self.tag)
        fields.addRow(tr("Folder"), self.folder)
        form.addRow(overrides)
        overrides.hide()
        advanced.toggled.connect(overrides.setVisible)
        self.error = QLabel()
        self.error.setTextFormat(Qt.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(480, 650)

    def effective_class(self):
        if self.cls.currentIndex() == 0:
            return self.inherited.get('class')
        return None if self.cls.currentIndex() == 1 else self.cls.currentText()

    def update_enums(self):
        cls = self.effective_class()
        self.predefined.clear()
        choices = [pt for schema in TABLES.get(cls, {}).get('schemas', [])
                   for pt in predefined_types(cls, schema)]
        self.predefined.addItems([tr("Inherit"), tr("None"), *dict.fromkeys(choices)])

    def add_code(self):
        systems = self.registry.get('classification_systems', {})
        system, ok = QInputDialog.getItem(self, tr("Classifications"), tr("System"), list(systems), editable=False)
        if not ok or system not in systems:
            return
        codes = systems[system].get('codes', {})
        code, ok = QInputDialog.getItem(self, tr("Classifications"), tr("Code"), list(codes), editable=False)
        if ok and code in codes:
            rows = json.loads(self.codes.toPlainText())
            if not any((r['system'], r['code']) == (system, code) for r in rows):
                rows.append(dict(system=system, code=code, name=codes[code]['name']))
                self.codes.setPlainText(json.dumps(rows))

    def submit(self):
        recipe = deepcopy(self.original)
        if self.cls.currentIndex() == 0:
            recipe.pop('class', None)
        else:
            recipe['class'] = self.effective_class()
        for field, picker in [('predefined_type', self.predefined), ('type', self.type_box)]:
            if picker.currentIndex() == 0:
                recipe.pop(field, None)
            else:
                recipe[field] = None if picker.currentIndex() == 1 else picker.currentText()
        codes = json.loads(self.codes.toPlainText())
        for entry in codes:
            if not entry.get('name'):
                entry.pop('name', None)
        for field, value in [('tag', self.tag.text().strip()), ('object_type', self.object_type.text()),
                             ('classes_allowed', [i.text() for i in self.allowed.selectedItems()]),
                             ('systems', json.loads(self.systems.toPlainText())),
                             ('classifications', codes)]:
            if value:
                recipe[field] = value
            elif recipe.get(field):
                recipe.pop(field)
        if self.folder.text() != self.folder_text:
            if self.folder.text().strip():
                recipe['folder'] = [s.strip() for s in self.folder.text().split(' / ')]
            else:
                recipe.pop('folder', None)
        cls = self.effective_class()
        status = self.status.currentText()
        props = recipe.get('psets', {}).get(self.old_pset, {})
        if not cls or common_pset(cls) != self.old_pset or not status:
            props.pop('Status', None)
        if cls and status:
            recipe.setdefault('psets', {}).setdefault(common_pset(cls), {})['Status'] = dict(kind='enum', value=status)
        try:
            update_node(self.viewport, self.key, name=self.name.text().strip(), recipe=recipe)
        except (ValueError, KeyError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
