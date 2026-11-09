# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Choose each document's renderer and detect starts that never presented.

The guard covers renderer creation/presentation only. Loading a document is
not a renderer failure, and environment-selected benchmark runs leave saved
preferences untouched.
"""
import logging
import os
from PySide6.QtCore import QSettings
from core import general_settings as settings

SETTING = 'viewport_renderer'
STARTING = 'viewport_renderer_starting'
DEFAULT = 'opengl'
_checked = False


def wanted(st=None):
    override = os.environ.get('INGETRAZO_WGPU')
    if override in ('0', '1'):
        return override == '1'
    return settings.value(SETTING, DEFAULT, st) == 'wgpu'


def start_guard(st=None):
    """Recover once per process, before choosing any document renderer."""
    global _checked
    if _checked or os.environ.get('INGETRAZO_WGPU') in ('0', '1'):
        return False
    _checked = True
    st = st if st is not None else QSettings()
    pending = str(settings.value(STARTING, '0', st)) == '1'
    if pending:
        settings.set_value(SETTING, DEFAULT, st)
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
