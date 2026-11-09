# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Choose each document's renderer and detect starts that never presented.

The guard covers renderer creation/presentation only. Loading a document is
not a renderer failure, and environment-selected benchmark runs leave saved
preferences untouched.
"""
import logging
import os
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from PySide6.QtCore import QSettings, qVersion
from core import general_settings as settings

SETTING = 'viewport_renderer'
STARTING = 'viewport_renderer_starting'
DEFAULT_RENDERER = 'opengl'
# Compatibility for callers outside the application. Selection uses the constant above.
DEFAULT = DEFAULT_RENDERER
_checked = False


@dataclass(frozen=True)
class Capability:
    available: bool
    reason: str = ''
    python_version: str = platform.python_version()
    qt_version: str = qVersion()


def _probe_local():
    """Child only: exercise this crate's actual adapter/device requirements."""
    try:
        import ingetrazo_render
    except Exception as exc:
        reason = f'render crate unavailable: {exc}'
        if sys.platform != 'darwin':
            reason = f'not validated on this platform (Metal only); {reason}'
        return Capability(False, reason)
    if sys.platform != 'darwin':
        return Capability(False, 'not validated on this platform (Metal only)')
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtCore import Qt
        app = QApplication.instance() or QApplication([])
        view = QWidget()
        view.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        view.resize(16, 16)
        renderer = ingetrazo_render.Renderer(int(view.winId()), 16, 16, 1.0)
        del renderer
        view.close()
        return Capability(True)
    except BaseException as exc:  # also catches PyO3's PanicException
        return Capability(False, f'Metal adapter/device unavailable: {exc}')


@lru_cache(maxsize=1)
def capability():
    """Probe once, before window construction, with a bounded crash boundary."""
    command = ([sys.executable, '--probe-metal'] if getattr(sys, 'frozen', False)
               else [sys.executable, '-m', 'core.renderer_settings'])
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=30, check=False)
        if result.returncode:
            return Capability(False, f'Metal probe exited with code {result.returncode}')
        # Qt/drivers may write diagnostics before our final JSON line.
        data = json.loads(result.stdout.strip().splitlines()[-1])
        return Capability(**data)
    except subprocess.TimeoutExpired:
        return Capability(False, 'Metal probe timed out')
    except (OSError, ValueError, IndexError, TypeError) as exc:
        return Capability(False, f'Metal probe failed: {exc}')


def requested(st=None):
    override = os.environ.get('INGETRAZO_WGPU')
    if override in ('0', '1'):
        return 'wgpu' if override == '1' else 'opengl'
    return settings.value(SETTING, DEFAULT_RENDERER, st)


def wanted(st=None):
    """Preference → environment → capability → persisted start recovery."""
    start_guard(st)
    return requested(st) == 'wgpu' and capability().available


def status_text(metal=None, st=None):
    if metal is None:
        metal = wanted(st)
    if metal:
        return 'Metal (wgpu)'
    cap = capability()
    if not cap.available:
        return f'OpenGL — Metal unavailable: {cap.reason}'
    return 'OpenGL'


def probe_main():
    from dataclasses import asdict
    print(json.dumps(asdict(_probe_local())), flush=True)


def start_guard(st=None):
    """Recover once per process, before choosing any document renderer."""
    global _checked
    if _checked or os.environ.get('INGETRAZO_WGPU') in ('0', '1'):
        return False
    _checked = True
    st = st if st is not None else QSettings()
    pending = str(settings.value(STARTING, '0', st)) == '1'
    if pending:
        settings.set_value(SETTING, 'opengl', st)
        settings.set_value(STARTING, '0', st)
        st.sync()
        logging.getLogger(__name__).warning(
            'The last Metal renderer start never presented a frame; using OpenGL.')
    return pending


def arm(st=None):
    """Call after loading, immediately before creating/presenting Metal."""
    if os.environ.get('INGETRAZO_WGPU') in ('0', '1'):
        return
    st = st if st is not None else QSettings()
    settings.set_value(STARTING, '1', st)
    st.sync()


def first_frame(st=None):
    """A successful presentation, not an elapsed-time deadline, clears it."""
    if os.environ.get('INGETRAZO_WGPU') in ('0', '1'):
        return
    st = st if st is not None else QSettings()
    settings.set_value(STARTING, '0', st)
    st.sync()


if __name__ == '__main__':
    probe_main()
