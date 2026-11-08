#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure cold/warm array takeoff and exports without building lazy meshes.

Run with QT_QPA_PLATFORM=offscreen. Outputs are written only to --output,
never alongside the input document. RSS is the process high-water mark.
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
from core.bim import collect_objects, _group_meshes
from formats import igz
from formats.ifc import save_ifc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    scene = Scene()

    def measure(label, fn):
        start = time.perf_counter()
        result = fn()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(json.dumps({'stage': label, 'seconds': time.perf_counter() - start,
                          'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024}), flush=True)
        return result

    measure('load', lambda: igz.load_into(scene, args.input))
    deferred = [m for m in _group_meshes(scene) if '_deferred' in m.__dict__]
    memo = {}
    objects = measure('collect cold', lambda: collect_objects(scene, memo))
    measure('collect warm', lambda: collect_objects(scene))
    measure('collect memo', lambda: collect_objects(scene, memo))
    print(json.dumps({'objects': len(objects), 'deferred_meshes': len(deferred)}), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    # Progress helps distinguish formatting time from collection and final I/O.
    import importlib
    exporter = importlib.import_module('formats.ifc.export')
    original_body = exporter.array_body
    bodies = 0

    def body(*args, **kwargs):
        nonlocal bodies
        result = original_body(*args, **kwargs)
        bodies += 1
        if bodies % 100 == 0:
            print(json.dumps({'bodies_written': bodies}), flush=True)
        return result

    exporter.array_body = body
    for geometry in ('brep', 'polygonal'):
        scene.plugin_data.setdefault('bim_registry', {}).setdefault('export_profiles', {})['array-benchmark'] = {'geometry': geometry}
        path = args.output / (geometry + '.ifc')
        report = measure(geometry, lambda: save_ifc(scene, path, profile='array-benchmark'))
        print(json.dumps({'geometry': geometry, 'bytes': path.stat().st_size,
                          'exported': int(report), 'problems': len(report.problems)}), flush=True)
        assert all('_deferred' in m.__dict__ for m in deferred)
    # Keep QApplication alive through all Qt-backed scene operations.
    del scene
    del app


if __name__ == '__main__':
    main()
