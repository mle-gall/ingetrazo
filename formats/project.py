# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable project JSON, replaced atomically so readers never see half a write."""
import json
import os
from pathlib import Path
import tempfile


def load(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Unsupported project version')
    for key in ('bim_registry', 'ifc_identity'):
        if not isinstance(value.get(key), dict):
            raise ValueError(key + ' must be an object')
    for key in ('files', 'links'):
        if not isinstance(value.get(key), list):
            raise ValueError(key + ' must be an array')
    import uuid
    uuid.UUID(value['ifc_identity'].get('namespace', ''))
    for entry in value['files']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or entry.get('role') not in ('host', 'linked', 'reference'):
            raise ValueError('files require path and host, linked or reference role')
    for edge in value['links']:
        if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) for k in ('host', 'source', 'placement_uid')):
            raise ValueError('links require host, source and placement_uid')
        from core.links import validate_select
        validate_select(edge.get('select'))
    session = value.get('worksession')
    if session is not None:
        if not isinstance(session, dict) or not isinstance(session.get('files'), list):
            raise ValueError('worksession requires a files array')
        paths = []
        for entry in session['files']:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                raise ValueError('worksession files require paths')
            camera = entry.get('camera')
            if camera is not None and not isinstance(camera, dict):
                raise ValueError('worksession camera must be an object')
            paths.append(entry['path'])
        active = session.get('active_file')
        if len(set(paths)) != len(paths) or (active is not None and active not in paths):
            raise ValueError('worksession requires unique files and an open active file')
    from core.bim_registry import validate
    errors = validate(value['bim_registry'])
    if errors:
        raise ValueError('; '.join(errors))
    return value


def save(path, value):
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
