# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only takeoff timing; separate processes keep both runs genuinely cold.

Run with INGETRAZO_RUST=1 QT_QPA_PLATFORM=offscreen. The optional native wheel
is not required. Output profiles and quantity snapshots stay in the worktree.
"""
import argparse
import cProfile
import json
import os
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--reference', type=Path, help='baseline quantity JSON to compare')
    args = parser.parse_args()
    from core.scene import Scene
    from core.bim import collect_objects, object_quantities
    from formats.igz import load_into
    scene = Scene()
    load_into(scene, args.model)
    memo = {}
    profile = cProfile.Profile()
    print('load averages:', os.getloadavg(), flush=True)
    start = perf_counter()
    profile.enable()
    objects = collect_objects(scene, memo)
    profile.disable()
    print('cold profiled collection:', perf_counter() - start, flush=True)
    profile.dump_stats(str(args.output) + '.prof')
    start = perf_counter()
    collect_objects(scene, memo)
    print('memo collection:', perf_counter() - start, flush=True)
    start = perf_counter()
    for obj in objects:
        object_quantities(obj)
    print('class quantities:', perf_counter() - start, flush=True)
    snapshot = [(obj['area'], obj['volume']) for obj in objects]
    Path(str(args.output) + '.json').write_text(json.dumps(snapshot))
    if args.reference is not None:
        import numpy as np
        expected = json.loads(args.reference.read_text())
        if len(expected) != len(snapshot):
            raise AssertionError('object count changed')
        mismatches = []
        for index, (before, after) in enumerate(zip(expected, snapshot)):
            if ((before[1] is None) != (after[1] is None)
                    or not np.allclose([v for v in before if v is not None],
                                       [v for v in after if v is not None],
                                       rtol=2e-5, atol=1e-7)):
                mismatches.append(index)
        print('quantity mismatches:', mismatches, flush=True)
        if mismatches:
            raise AssertionError('quantities differ from the reference')
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from views.tray import BimPanel
    app = QApplication.instance() or QApplication([])
    panel = BimPanel(SimpleNamespace(viewport=SimpleNamespace(scene=scene)))
    panel._measure_all = True
    panel.__dict__.pop('_takeoff_key', None)
    start = perf_counter()
    panel.refresh()
    print('tray refresh, warm arrays/fresh memo:', perf_counter() - start, flush=True)
    panel.close()
    app.processEvents()


if __name__ == '__main__':
    main()
