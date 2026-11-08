# SPDX-License-Identifier: GPL-3.0-or-later
"""Project favourites and a searchable domain list share one class chooser."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
from core.bim_registry import ordered_classes
from core.ifc_tables import TABLES


class ClassPicker(QComboBox):
    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.addItems(ordered_classes(registry))
        self.insertSeparator(self.count())
        self.addItem('All classes…')
        self.activated.connect(self._pick)

    def _pick(self, index):
        if self.itemText(index) != 'All classes…':
            return
        self.setCurrentIndex(0)
        dialog = QDialog(self)
        dialog.setWindowTitle('IFC classes')
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText('Filter class or domain')
        rows = QListWidget()
        layout.addWidget(search)
        layout.addWidget(rows)
        for cls in sorted(TABLES, key=lambda c: (TABLES[c]['domain'], c)):
            item = QListWidgetItem(TABLES[cls]['domain'] + ' — ' + cls)
            item.setData(Qt.ItemDataRole.UserRole, cls)
            rows.addItem(item)
        def filter_rows(text):
            for i in range(rows.count()):
                item = rows.item(i)
                item.setHidden(text.casefold() not in item.text().casefold())
        search.textChanged.connect(filter_rows)
        rows.itemActivated.connect(lambda item: (self.setCurrentText(item.data(Qt.ItemDataRole.UserRole)), dialog.accept()))
        dialog.exec()
