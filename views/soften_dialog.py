# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QDoubleSpinBox, QCheckBox, QDialogButtonBox)
from core.i18n import tr


class SoftenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Soften / Smooth Edges'))
        layout = QVBoxLayout(self)
        hint = QLabel(tr('Edges at or below this angle become smooth; sharper edges stay hard. '
                        'Selected groups include their nested geometry. Component copies share the change.'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Angle between faces')))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1800)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(0, 180)
        self.angle.setDecimals(1)
        self.angle.setSuffix('°')
        self.slider.valueChanged.connect(lambda v: self.angle.setValue(v / 10))
        self.angle.valueChanged.connect(lambda v: self.slider.setValue(round(v * 10)))
        self.angle.setValue(float(QSettings().value('tools/soften_angle', 30)))
        row.addWidget(self.slider)
        row.addWidget(self.angle)
        layout.addLayout(row)
        self.coplanar = QCheckBox(tr('Soften coplanar edges'))
        self.coplanar.setChecked(True)
        layout.addWidget(self.coplanar)
        self.harden = QCheckBox(tr('Unsoften all selected edges'))
        self.harden.toggled.connect(lambda on: self.angle.setEnabled(not on))
        self.harden.toggled.connect(lambda on: self.slider.setEnabled(not on))
        self.harden.toggled.connect(lambda on: self.coplanar.setEnabled(not on))
        layout.addWidget(self.harden)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(470, 190)
