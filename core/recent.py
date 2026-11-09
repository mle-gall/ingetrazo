# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, pinnable recent paths retain missing entries for relocation."""
import json
from pathlib import Path
from PySide6.QtCore import QSettings

LIMIT = 20


def entries(kind='files', settings=None):
    st = settings or QSettings()
    try:
        rows = json.loads(st.value('home/recent_' + kind, '[]'))
    except (TypeError, ValueError):
        rows = []
    if not rows and kind == 'files':
        old = st.value('recent_files', []) or []
        rows = [{'path': p, 'pinned': False} for p in ([old] if isinstance(old, str) else old)]
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get('path'), str)][:LIMIT]


def remember(path, pinned=None, settings=None, replace=None):
    st = settings or QSettings()
    path = str(Path(path).resolve())
    kind = 'projects' if Path(path).suffix.lower() == '.igzproj' else 'files'
    rows = entries(kind, st)
    previous = next((r for r in rows if r['path'] in (path, replace)), {})
    row = {'path': path, 'pinned': previous.get('pinned', False) if pinned is None else bool(pinned)}
    rows = [row] + [r for r in rows if r['path'] not in (path, replace)]
    rows.sort(key=lambda r: not r.get('pinned', False))
    st.setValue('home/recent_' + kind, json.dumps(rows[:LIMIT]))


def query(settings=None):
    return {kind: entries(kind, settings) for kind in ('files', 'projects')}
