# SPDX-License-Identifier: GPL-3.0-or-later
"""Translate wheel/trackpad input into the viewport's zoom convention."""
import sys

from PySide6.QtGui import QInputDevice


def zoom_steps(event, invert=False):
    steps = event.angleDelta().y() / 120.0
    # Cocoa applies Natural Scrolling to trackpad deltas. Undo that OS
    # reversal for physical gesture zoom; keep other platforms and ordinary
    # mouse wheels unchanged. The user's explicit override applies last.
    if (sys.platform == "darwin"
            and event.device().type() == QInputDevice.DeviceType.TouchPad
            and event.inverted()):
        steps = -steps
    return -steps if invert else steps
