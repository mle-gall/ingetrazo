"""Measure resident update submission and paced frames on a read-only model."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_AO'] = '0'
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMatrix4x4
from core.scene import Scene
from core.history import History, MoveGroupCommand, TagGroupsCommand, InsertGroupCommand
from PySide6.QtGui import QVector3D
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
view._inference_future.result()
for _ in range(20):
    view.draw_frame()
    app.processEvents()
    time.sleep(.016)
view.pick_row(0, 0)
history = History(scene)
view._instance_updates.observe(history)


class Counted:
    def __init__(self, renderer):
        self.renderer = renderer
        self.calls = {}
        self.rows = []

    def __getattr__(self, name):
        method = getattr(self.renderer, name)
        def invoke(*args):
            self.calls[name] = self.calls.get(name, 0) + 1
            if name == "update_instances":
                self.rows.append(len(args[0]))
            return method(*args)
        return invoke


renderer = Counted(view.renderer)
view.renderer = renderer
result = {'placements': len(view.packed.instances)}
g = next(g for g in scene.groups if g.xform is not None and not g.children
         and view._instance_updates.meshes[id(g.mesh)][2] >= 0)
start = time.perf_counter()
history.execute(MoveGroupCommand(g, QVector3D(.01, 0, 0)))
command_end = time.perf_counter()
view.set_scene(scene)
result['move_history_ms'] = (command_end-start)*1000
result['move_submission_ms'] = (time.perf_counter()-command_end)*1000
result['move_update_ms'] = (time.perf_counter()-start)*1000
result['move_calls'] = dict(renderer.calls)
result['move_row_counts'] = list(renderer.rows)
view.draw_frame()
view.pick_row(0, 0)
result['move_gpu_complete_ms'] = (time.perf_counter()-start)*1000
renderer.rows.clear()
renderer.calls.clear()
start = time.perf_counter()
history.execute(TagGroupsCommand(scene.groups[:1000], 'IfcBuildingElementProxy'))
view.set_scene(scene)
result['record_update_ms'] = (time.perf_counter()-start)*1000
result['record_calls'] = dict(renderer.calls)
renderer.calls.clear()
added = Group(next(group.mesh for group in view.packed.groups if group is not None))
added.xform = QMatrix4x4()
start = time.perf_counter()
history.execute(InsertGroupCommand(added))
view.set_scene(scene)
result['add_update_ms'] = (time.perf_counter()-start)*1000
result['add_calls'] = dict(renderer.calls)
result['add_row_counts'] = list(renderer.rows)
renderer.rows.clear()
# Isolate the resident matrix preview and paced frame cost from scene scanning.
ids = np.arange(min(1000, len(view.packed.instances)))
original = view.packed.instances[ids].copy()
# Preparation is excluded from this isolated matrix-path diagnostic.
app.processEvents()
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
renderer.update_instances(ids.tolist(), original.view(np.uint8).reshape(-1))
# Exercise the dispatched Move hover, resident preview, overlay and frame.
from types import SimpleNamespace
from PySide6.QtCore import QPointF, Qt
from tools.move import MoveTool
source = SimpleNamespace(scene=scene, _horizon_ndc_y=lambda mvp: 0., camera=view.camera, active_tool=MoveTool(), history=history,
    view_tint={}, inference=None, linear_inference_mode='all',
    flash_status=lambda *a: None, measurementChanged=SimpleNamespace(emit=lambda *a: None),
    _measurement_text=lambda: '', _effective_style=lambda: scene.display_style)
view.source_viewport = source
selected = [g for g in view.packed.groups if g is not None and not g.children][:1000]
scene.select(selected)
view.draw_frame()
pixel = None
for y in range(100, 601, 100):
    for x in range(100, 901, 100):
        if view.pick_row(x, y) is not None:
            pixel = (x, y)
            break
    if pixel is not None:
        break
if pixel is not None:
    event = SimpleNamespace(position=lambda: QPointF(*pixel), modifiers=lambda: Qt.NoModifier)
    view.hover(*pixel)
    view.tools.click(event)
    # Present pickup (including the zero-distance label) before dragging.
    view.draw_frame()
    view.pick_row(0, 0)
    result['drag_placements'] = len(view.tools.ids)
    drag_frames = []
    for i in range(30):
        pixel = (pixel[0] + (1 if i % 2 else -1), pixel[1])
        start = time.perf_counter()
        view.hover(*pixel)
        hovered = time.perf_counter()
        view.tools.hover(event)
        previewed = time.perf_counter()
        frame = view.draw_frame()
        drag_frames.append({'wall_ms': (time.perf_counter()-start)*1000, 'gpu_ms': frame[1],
                            'hover_ms': (hovered-start)*1000,
                            'preview_ms': (previewed-hovered)*1000,
                            'frame_ms': (time.perf_counter()-previewed)*1000,
                            'overlay_ms': view.overlay_ms})
        time.sleep(.016)
    result['dispatched_drag_frames'] = drag_frames
    view.tools.cancel()
print(json.dumps(result, indent=2))
view.close()
