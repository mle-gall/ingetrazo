# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional IDS validation never makes the native exporter depend on IfcTester."""
import json
from pathlib import Path


def check_ids(path, files, project_directory=None):
    if not files:
        return []
    reports = []
    try:
        import ifcopenshell
        from ifctester import ids
    except ImportError:
        reports = [{'status': 'unavailable', 'message': 'ifctester is not installed'}]
    else:
        model = ifcopenshell.open(str(path))
        for filename in files:
            source = Path(filename)
            if not source.is_absolute():
                source = Path(project_directory or Path(path).parent) / source
            try:
                requirements = ids.open(str(source))
                requirements.validate(model)
                reports.append({'file': str(source), 'status': 'checked', 'specifications': [
                    {'name': spec.name, 'passed': len(set(spec.applicable_entities) - spec.failed_entities),
                     'failed': len(spec.failed_entities), 'status': spec.status}
                    for spec in requirements.specifications]})
            except Exception as exc:
                reports.append({'file': str(source), 'status': 'error', 'message': str(exc)})
    Path(path).with_suffix('.ids-report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    return reports
