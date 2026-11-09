"""Bounded, read-only-model push/pull commit-to-native-frame measurement."""
import os
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_AO'] = '0'
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D
from PySide6.QtCore import QPointF, Qt
from core.scene import Scene
from core.group import iter_placements
from core.history import History
from formats.igz import load_into
from tools.base import ToolContext
from tools.pushpull import PushPullTool
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
view.renderer.set_antialias(False)
group = next(g for root in scene.groups for g, _ in iter_placements(root)
             if not g.children and len(g.mesh.faces) and len(g.mesh.faces) < 100)
scene.begin_group_edit(group)
view.set_scene(scene)
face = scene.mesh.faces[0]
view.camera.target = face.centroid()
view.camera.distance = max(2., (face.vertices[0]-view.camera.target).length()*6)
for _ in range(3):
    view.draw_frame()
# A real Push/Pull gesture acquires the ID target before committing.
view.pick_row(0, 0)
history = History(scene)
view._instance_updates.observe(history)
vp = SimpleNamespace(scene=scene, history=history, camera=view.camera,
    update=lambda: None, set_hover=lambda *a: None, set_suppressed_faces=lambda *a: None,
    flash_status=lambda *a: None)
results = []
for i in range(3):
    face = scene.mesh.faces[0]
    tool = PushPullTool()
    tool.hovered_face = face
    tool.on_click(ToolContext(vp, face.centroid(), QPointF(), Qt.NoModifier, None))
    start = time.perf_counter()
    tool.on_value(vp, .01)
    committed = time.perf_counter()
    view.set_scene(scene)
    baked = len(view._instance_updates.changed)
    submitted = time.perf_counter()
    view.draw_frame()
    view.pick_row(0, 0)  # synchronous readback: GPU completed the result frame
    results.append(dict(command_ms=(committed-start)*1000,
        commit_to_frame_ms=(time.perf_counter()-committed)*1000,
        diff_ms=(submitted-committed)*1000, prototypes=baked))
    history.undo()
    view.set_scene(scene)
    view.draw_frame()
print(json.dumps(dict(model=Path(sys.argv[1]).name, group=group.name,
    placements=len(view.packed.instances), samples=results), indent=2), flush=True)
view.close()
