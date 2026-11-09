"""Bounded one-triangle CPU-floor diagnostic, at the same 2x capture size."""
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
from core.mesh import Mesh
from core.group import Group
from core.scene import Scene
from views.wgpu_view import WgpuView

app = QApplication([])
view = WgpuView()
view.resize(1000, 700)
mesh = Mesh()
mesh.add_face([QVector3D(-1, -1, 0), QVector3D(1, -1, 0), QVector3D(0, 1, 0)])
view.set_scene(Scene(groups=[Group(mesh)]))
view.show()


def measure():
    try:
        view.draw_frame()
        result = {'size': [int(view.width()*view.devicePixelRatioF()),
                           int(view.height()*view.devicePixelRatioF())]}
        for present in (True, False):
            samples = []
            for i in range(60):
                before = time.perf_counter()
                cpu, gpu = view.renderer.render(present)
                wall = (time.perf_counter()-before)*1000
                if i >= 15:
                    samples.append([cpu, gpu or 0., wall, *view.renderer.frame_stage_timings()])
            result[str(present)] = dict(zip(
                ('cpu', 'gpu', 'wall', 'poll', 'acquire', 'encode', 'submit', 'present'),
                np.median(samples, axis=0).tolist()))
        out = Path('docs/benchmarks/wgpu-look-2026-11-09/r-look-3c/tiny.json')
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        view.close()
        app.quit()

QTimer.singleShot(1000, measure)
QTimer.singleShot(30000, app.quit)
app.exec()
