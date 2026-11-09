# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Run a panel's refresh iterator in short Qt event-loop slices."""
from time import monotonic

from PySide6.QtCore import QTimer


def refresh_steps(panel, steps, *, deferred, current):
    # An explicit refresh supersedes any pending one (including a refresh
    # of the same scene/version after a filter or sort change).
    panel._pending_refresh = steps

    def advance():
        if panel._pending_refresh is not steps:
            return
        if not current():
            panel._pending_refresh = None
            return
        deadline = monotonic() + 0.018
        for _ in steps:
            if deferred and monotonic() >= deadline:
                QTimer.singleShot(12, panel, advance)
                return
        panel._pending_refresh = None

    advance()
