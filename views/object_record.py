# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact object and project metadata editors."""
import json
from copy import deepcopy
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QComboBox,
    QLineEdit, QPlainTextEdit, QLabel, QPushButton, QFileDialog, QInputDialog,
    QTableWidget, QListWidget)
from core import record, bim_registry
from core.ifc_tables import TABLES, IFC_CLASSES, STATUS, predefined_types, common_pset


class ClassificationRows(QTableWidget):
    def __init__(self, rows):
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels(['System', 'Code', 'Name'])
        self.setPlainText(json.dumps(rows))

    def setPlainText(self, text):
        from PySide6.QtWidgets import QTableWidgetItem
        self.rows = json.loads(text)
        self.setRowCount(len(self.rows))
        for row, value in enumerate(self.rows):
            for col, key in enumerate(('system', 'code', 'name')):
                self.setItem(row, col, QTableWidgetItem(value.get(key, '')))

    def toPlainText(self):
        return json.dumps([{**self.rows[row], **{key: self.item(row, col).text()
            for col, key in enumerate(('system', 'code', 'name'))}}
            for row in range(self.rowCount())])

    def remove_selected(self):
        rows = json.loads(self.toPlainText())
        selected = {index.row() for index in self.selectedIndexes()}
        self.setPlainText(json.dumps([value for i, value in enumerate(rows) if i not in selected]))


class SystemMembership(QListWidget):
    def __init__(self, selected, registry):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem
        super().__init__()
        for key in dict.fromkeys([*registry.get('systems', {}), *selected]):
            item = QListWidgetItem(key, self)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)

    def toPlainText(self):
        from PySide6.QtCore import Qt
        return json.dumps([self.item(i).text() for i in range(self.count())
                           if self.item(i).checkState() == Qt.Checked])


class RecordDialog(QDialog):
    """Edit a detached patch; apply the same visible fields to all targets."""
    def __init__(self, parent, initial, registry):
        super().__init__(parent)
        self.setWindowTitle('Object record')
        self.registry = registry
        # A fresh record must at least carry its class; an existing one only
        # receives the fields the user changed, so that one dialog applied
        # to a multi-selection never copies the first object's name onto
        # the others.
        self._fresh = not initial
        self.initial = deepcopy(initial or {'class': 'IfcWall'})
        self.patch = None
        form = QFormLayout(self)
        self.schema = QComboBox(); self.schema.addItems(['IFC4', 'IFC4X3_ADD2'])
        form.addRow('Schema for validation', self.schema)
        from views.ifc_picker import ClassPicker
        self.cls = ClassPicker(registry)
        self.cls.setCurrentText(self.initial['class']); form.addRow('Class', self.cls)
        self.predefined = QComboBox(); form.addRow('PredefinedType', self.predefined)
        self.fields = {}
        for key in ('object_type', 'name', 'tag', 'description'):
            field = QLineEdit(self.initial.get(key, ''))
            self.fields[key] = field; form.addRow(key, field)
        self.type_box = QComboBox(); self.type_box.addItem('')
        self.type_box.addItems(list(registry.get('types', {})))
        self.type_box.setCurrentText(self.initial.get('type') or '')
        form.addRow('Type', self.type_box)
        self.status = QComboBox(); self.status.addItems([''] + STATUS)
        status = self.initial.get('psets', {}).get(common_pset(self.initial['class']), {}).get('Status', '')
        self.status.setCurrentText(status.get('value', '') if isinstance(status, dict) else status)
        form.addRow('Status', self.status)
        self.json_fields = {}
        for key, default in [('classifications', []), ('systems', []), ('psets', {}), ('quantities', {})]:
            if key == 'classifications':
                field = ClassificationRows(self.initial.get(key, []))
            elif key == 'systems':
                field = SystemMembership(self.initial.get(key, []), registry)
            else:
                field = QPlainTextEdit(json.dumps(self.initial.get(key, default), indent=2))
            field.setMaximumHeight(90)
            self.json_fields[key] = field; form.addRow(key + (' (JSON)' if key in ('psets', 'quantities') else ''), field)
        add = QPushButton('Add classification…'); form.addRow(add)
        add.clicked.connect(self.add_classification)
        remove = QPushButton('Remove selected classifications')
        form.addRow(remove)
        remove.clicked.connect(self.json_fields['classifications'].remove_selected)
        pset = QPushButton('Add property…'); form.addRow(pset)
        pset.clicked.connect(self.add_property)
        self.error = QLabel(); self.error.setWordWrap(True); form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit); buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.cls.currentTextChanged.connect(self.update_enums)
        self.schema.currentTextChanged.connect(self.update_enums)
        self.predefined.currentTextChanged.connect(lambda text: self.fields['object_type'].setVisible(text == 'USERDEFINED'))
        self.update_enums()
        self.predefined.setCurrentText(self.initial.get('predefined_type') or '')

    def update_enums(self, *_):
        old = self.predefined.currentText()
        self.predefined.clear()
        self.predefined.addItems([''] + predefined_types(self.cls.currentText(), self.schema.currentText()))
        self.predefined.setCurrentText(old)
        self.fields['object_type'].setVisible(self.predefined.currentText() == 'USERDEFINED')
        self.status.setEnabled('Status' in TABLES[self.cls.currentText()]['common'])

    def add_classification(self):
        systems = self.registry.get('classification_systems', {})
        key, ok = QInputDialog.getItem(self, 'Classification', 'System', list(systems), editable=False)
        if not ok: return
        codes = systems[key].get('codes', {})
        code, ok = QInputDialog.getItem(self, 'Classification', 'Code', list(codes), editable=True)
        if not ok: return
        name, ok = QInputDialog.getText(self, 'Classification', 'Name', text=codes.get(code, {}).get('name', ''))
        if not ok: return
        try:
            rows = json.loads(self.json_fields['classifications'].toPlainText())
            rows.append({'system': key, 'code': code, 'name': name})
            self.json_fields['classifications'].setPlainText(json.dumps(rows, indent=2))
        except (ValueError, AttributeError) as exc: self.error.setText(str(exc))

    def add_property(self):
        pset, ok = QInputDialog.getText(self, 'Property', 'Property set')
        if not ok or not pset: return
        prop, ok = QInputDialog.getText(self, 'Property', 'Property name')
        if not ok or not prop: return
        kind, ok = QInputDialog.getItem(self, 'Property', 'Kind', record.KINDS, editable=False)
        if not ok: return
        text, ok = QInputDialog.getText(self, 'Property', 'Value (JSON for numbers/boolean)')
        if not ok: return
        try:
            value = text if kind in ('text', 'label', 'enum') else json.loads(text)
            psets = json.loads(self.json_fields['psets'].toPlainText())
            psets.setdefault(pset, {})[prop] = {'kind': kind, 'value': value}
            self.json_fields['psets'].setPlainText(json.dumps(psets, indent=2))
        except (ValueError, AttributeError) as exc: self.error.setText(str(exc))

    def submit(self):
        try:
            patch = {key: field.text() for key, field in self.fields.items()}
            patch.update({key: json.loads(field.toPlainText()) for key, field in self.json_fields.items()})
            patch.update({'class': self.cls.currentText(), 'predefined_type': self.predefined.currentText() or None,
                          'type': self.type_box.currentText() or None})
            if self.status.isEnabled() and self.status.currentText():
                patch['psets'].setdefault(common_pset(patch['class']), {})['Status'] = {'kind': 'enum', 'value': self.status.currentText()}
            elif isinstance(patch['psets'], dict):
                patch['psets'].get(common_pset(patch['class']), {}).pop('Status', None)
            errors = record.validate({**self.initial, **patch}, self.registry, self.schema.currentText())
            if errors: raise ValueError('\n'.join(errors))
        except (ValueError, TypeError, AttributeError) as exc:
            self.error.setText(str(exc)); return
        self.patch = self._changed(patch)
        self.accept()

    _DEFAULTS = {'object_type': '', 'name': '', 'tag': '', 'description': '',
                 'predefined_type': None, 'type': None, 'classifications': [],
                 'systems': [], 'psets': {}, 'quantities': {}}

    def _changed(self, full):
        """The part of ``full`` that differs from the record the dialog
        opened on; unchanged fields stay out so other selected groups keep
        theirs. A fresh record always carries its class."""
        before = record.normalize(self.initial)
        after = record.normalize(full)
        patch = {key: value for key, value in after.items()
                 if before.get(key, self._DEFAULTS.get(key)) != value}
        if self._fresh:
            patch['class'] = full['class']
        return patch


class RegistryDialog(QDialog):
    def __init__(self, parent, registry):
        super().__init__(parent)
        self.setWindowTitle('Project registry')
        self.resize(640, 650)
        self.value = None
        form = QFormLayout(self)
        self.editor = QPlainTextEdit(json.dumps(registry, indent=2, ensure_ascii=False))
        form.addRow(self.editor)
        add = QPushButton('New classification namespace…'); form.addRow(add)
        add.clicked.connect(self.add_namespace)
        csv = QPushButton('Import classification codes CSV…'); form.addRow(csv)
        csv.clicked.connect(self.import_csv)
        self.error = QLabel(); self.error.setWordWrap(True); form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit); buttons.rejected.connect(self.reject); form.addRow(buttons)

    def add_namespace(self):
        key, ok = QInputDialog.getText(self, 'Namespace', 'Registry key')
        if not ok or not key: return
        name, ok = QInputDialog.getText(self, 'Namespace', 'Name')
        if not ok: return
        try:
            value = json.loads(self.editor.toPlainText())
            if key in value['classification_systems']: raise ValueError('Key already exists')
            value = bim_registry.add_system(value, key, {'name': name, 'edition': '', 'source': '', 'description': ''}, classification=True)
            self.editor.setPlainText(json.dumps(value, indent=2))
        except (ValueError, KeyError, TypeError) as exc: self.error.setText(str(exc))

    def import_csv(self):
        try:
            value = json.loads(self.editor.toPlainText())
            key, ok = QInputDialog.getItem(self, 'CSV', 'Classification system', list(value['classification_systems']), editable=False)
            if not ok: return
            path, _ = QFileDialog.getOpenFileName(self, 'Codes CSV', '', 'CSV (*.csv)')
            if not path: return
            with open(path, encoding='utf-8-sig', newline='') as stream:
                value = bim_registry.import_codes_csv(value, key, stream.read())
            self.editor.setPlainText(json.dumps(value, indent=2))
        except (OSError, ValueError, KeyError, TypeError) as exc: self.error.setText(str(exc))

    def submit(self):
        try:
            value = json.loads(self.editor.toPlainText())
            errors = bim_registry.validate(value)
            if errors: raise ValueError('\n'.join(errors))
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc)); return
        self.value = value
        self.accept()
