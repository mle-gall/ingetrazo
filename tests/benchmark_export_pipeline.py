#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure one export profile per process so its RSS has an independent peak.

The source document is read only. Run offscreen with the optional IFC packages
installed; only --output is written. Cold/warm/memo stages precede the export.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.bim import collect_objects
from formats import igz
from formats.ifc import save_ifc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--geometry', choices=('brep', 'polygonal'), default='brep')
    parser.add_argument('--instancing', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    scene = Scene()

    def measure(stage, operation):
        start = time.perf_counter()
        result = operation()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(json.dumps({'stage': stage, 'seconds': time.perf_counter() - start,
                          'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024}), flush=True)
        return result

    measure('load', lambda: igz.load_into(scene, args.input))
    memo = {}
    measure('collect cold', lambda: collect_objects(scene, memo))
    measure('collect warm', lambda: collect_objects(scene))
    measure('collect memo', lambda: collect_objects(scene, memo))
    scene.plugin_data.setdefault('bim_registry', {}).setdefault('export_profiles', {})['P8'] = {
        'geometry': args.geometry, 'instancing': args.instancing}
    report = measure('export', lambda: save_ifc(scene, args.output, profile='P8'))
    print(json.dumps({'geometry': args.geometry, 'instancing': args.instancing,
                      'bytes': args.output.stat().st_size, 'exported': int(report),
                      'problems': len(report.problems)}), flush=True)
    del scene
    del app


if __name__ == '__main__':
    main()
