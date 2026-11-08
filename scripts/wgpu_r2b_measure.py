"""Measure resident update submission and paced frames on a read-only model."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMatrix4x4
from core.scene import Scene
from core.group import Group
from formats.igz import load_into
from views.wgpu_view import WgpuView

app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
view.show()
app.processEvents()
view.draw_frame()


class Counted:
    def __init__(self, renderer):
        self.renderer = renderer
        self.calls = {}

    def __getattr__(self, name):
        method = getattr(self.renderer, name)
        def invoke(*args):
            self.calls[name] = self.calls.get(name, 0) + 1
            return method(*args)
        return invoke


renderer = Counted(view.renderer)
view.renderer = renderer
result = {'placements': len(view.packed.instances)}
g = next(g for g in scene.groups if g.xform is not None)
g.xform = QMatrix4x4(g.xform)
g.xform.translate(.01, 0, 0)
scene.version += 1
start = time.perf_counter()
view.set_scene(scene)
result['move_update_ms'] = (time.perf_counter()-start)*1000
result['move_calls'] = dict(renderer.calls)
renderer.calls.clear()
for g in scene.groups[:1000]:
    g.ifc = {'class': 'IfcBuildingElementProxy'}
scene.version += 1
start = time.perf_counter()
view.set_scene(scene)
result['record_update_ms'] = (time.perf_counter()-start)*1000
result['record_calls'] = dict(renderer.calls)
renderer.calls.clear()
added = Group(next(group.mesh for group in view.packed.groups if group is not None))
scene.groups.append(added)
scene.version += 1
start = time.perf_counter()
view.set_scene(scene)
result['add_update_ms'] = (time.perf_counter()-start)*1000
result['add_calls'] = dict(renderer.calls)
# Isolate the resident matrix preview and paced frame cost from scene scanning.
ids = np.arange(min(1000, len(view.packed.instances)))
original = view.packed.instances[ids].copy()
# Preparation is excluded from this isolated matrix-path diagnostic.
future = getattr(view, '_inference_future', None)
if future is not None:
    future.result()
for _ in range(20):
    view.draw_frame()
    app.processEvents()
    time.sleep(.016)
frames = []
for i in range(50):
    rows = original.copy()
    rows['world'][:, 3, 0] += i*.001
    start = time.perf_counter()
    renderer.update_instances(ids.tolist(), rows.view(np.uint8).reshape(-1))
    frame = view.draw_frame()
    frames.append({'wall_ms': (time.perf_counter()-start)*1000, 'gpu_ms': frame[1]})
    app.processEvents()
    time.sleep(.016)
result['matrix_preview_frames'] = frames
print(json.dumps(result, indent=2))
view.close()
