# SPDX-License-Identifier: GPL-3.0-or-later
"""Read user-owned PSD XML on demand; no definition library is distributed."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

_CACHE = {}


def load(path):
    directory = Path(path).expanduser()
    files = sorted(directory.rglob('*.xml'))
    stamp = (directory.stat().st_mtime_ns, tuple((str(p), p.stat().st_mtime_ns) for p in files))
    key = str(directory.resolve())
    if key in _CACHE and _CACHE[key][0] == stamp:
        return deepcopy(_CACHE[key][1])
    result = {}
    for file in files:
        root = ET.parse(file).getroot()
        for node in root.iter():
            node.tag = node.tag.rsplit('}', 1)[-1]
        name = root.findtext('Name')
        if not name:
            continue
        properties = {}
        for prop in root.findall('./PropertyDefs/PropertyDef'):
            prop_name = prop.findtext('Name')
            if not prop_name:
                continue
            datatype = prop.find('.//DataType')
            datatype = datatype.get('type', '') if datatype is not None else ''
            kind = {'IfcBoolean': 'boolean', 'IfcInteger': 'integer', 'IfcLabel': 'label',
                    'IfcText': 'text', 'IfcLengthMeasure': 'length', 'IfcPositiveLengthMeasure': 'length',
                    'IfcAreaMeasure': 'area', 'IfcVolumeMeasure': 'volume'}.get(datatype, 'real')
            members = [item.text for item in prop.findall('.//EnumItem') if item.text]
            properties[prop_name] = {'kind': 'enum' if members else kind}
            if members:
                properties[prop_name]['members'] = members
        result[name] = {'properties': properties, 'applicable_classes': [n.text for n in root.findall('./ApplicableClasses/ClassName') if n.text]}
    _CACHE[key] = stamp, result
    return deepcopy(result)


def templates(registry):
    path = registry.get('pset_library', {}).get('path')
    return load(path) if path else {}
