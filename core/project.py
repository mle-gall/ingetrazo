# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared registry ownership; documents keep a portable reference and fallback.

Readers refresh from disk. Writers compare the last observed mtime, warn on a
conflict, and replace the registry as a whole (including history undo/redo).
"""
from copy import deepcopy
from pathlib import Path
import os
import uuid
import warnings

from formats import project as storage


def path_for(scene, host_path=None):
    ref = scene.plugin_data.get('project')
    if not isinstance(ref, dict):
        return None
    host = host_path or getattr(scene, '_project_host_path', None)
    if host and ref.get('rel'):
        candidate = Path(host).resolve().parent / ref['rel']
        if candidate.is_file():
            return candidate.resolve()
    return Path(ref['path']) if ref.get('path') else None


def read(scene):
    path = path_for(scene)
    if path is None or not path.is_file():
        return None
    value = storage.load(path)
    scene._project_mtime_ns = path.stat().st_mtime_ns
    return value


def attach(scene, path, host_path=None):
    path = Path(path).resolve()
    value = storage.load(path)
    scene.plugin_data['project'] = {'path': str(path)}
    refresh_reference(scene, host_path)
    scene._project_mtime_ns = path.stat().st_mtime_ns
    scene.plugin_data['ifc_identity'] = deepcopy(value['ifc_identity'])
    scene.version += 1
    return value


def refresh_reference(scene, host_path):
    path = path_for(scene)
    if path is not None and host_path:
        scene.plugin_data['project']['rel'] = os.path.relpath(path, Path(host_path).resolve().parent)
        scene._project_host_path = str(host_path)


def create(scene, path, host_path=None):
    from core.bim_registry import get
    from core.ifc_identity import stable_guid
    identity = deepcopy(scene.plugin_data.get('ifc_identity', {}))
    identity.setdefault('namespace', uuid.uuid4().hex)
    for key in ('project', 'site', 'building', 'storey'):
        identity.setdefault(key, stable_guid(identity['namespace'], key))
    value = dict(version=1, bim_registry=get(scene), ifc_identity=identity, files=[], links=[])
    storage.save(path, value)
    attach(scene, path, host_path)
    sync_files(scene, host_path)
    return value


def _write(scene, path, value):
    stamp = Path(path).stat().st_mtime_ns
    previous = getattr(scene, '_project_mtime_ns', stamp)
    if stamp != previous:
        message = 'Project changed in another document; last writer wins: ' + str(path)
        scene.project_warning = message
        warnings.warn(message, RuntimeWarning, stacklevel=2)
    storage.save(path, value)
    scene._project_mtime_ns = Path(path).stat().st_mtime_ns


def write_registry(scene, registry):
    path = path_for(scene)
    if path is None:
        return False
    # Missing project files must never be silently overwritten with a fallback.
    value = storage.load(path)
    value['bim_registry'] = deepcopy(registry)
    _write(scene, path, value)
    scene.plugin_data['bim_registry'] = deepcopy(registry)
    return True


def sync_files(scene, host_path):
    path = path_for(scene)
    if path is None or not path.is_file() or not host_path:
        return
    from core.links import linked_groups, link_of
    value = storage.load(path)
    def relative(p):
        return os.path.relpath(Path(p).resolve(), path.parent)
    host = relative(host_path)
    files = {entry['path']: entry for entry in value['files']}
    files[host] = dict(path=host, role='host')
    edges = [edge for edge in value['links'] if edge['host'] != host]
    for group in linked_groups(scene):
        rec = link_of(group)
        source = relative(rec['path'])
        files.setdefault(source, dict(path=source, role='linked'))
        edges.append(dict(host=host, source=source, placement_uid=group.uid,
                          select=deepcopy(rec.get('select'))))
    value['files'], value['links'] = list(files.values()), edges
    _write(scene, path, value)
