"""Bounded, reproducible resident-scene orbit measurement on a native Qt view."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ.setdefault('INGETRAZO_TEXTURE_CACHE', str(Path('.spike-results/textures').resolve()))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_view import WgpuView


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', type=Path)
    parser.add_argument('--measure', action='store_true')
    args = parser.parse_args()
    import faulthandler
    faulthandler.dump_traceback_later(60, repeat=True)
    app = QApplication([])
    window = QMainWindow()
    view = WgpuView()
    window.setCentralWidget(view)
    label = QLabel('Preparing resident scene')
    window.statusBar().addWidget(label)
    window.resize(1000, 700)
    start = time.perf_counter()
    scene = Scene()
    load_into(scene, args.model)
    loaded = time.perf_counter()
    print('loaded', loaded-start, flush=True)
    view.set_scene(scene)
    window.show()
    app.processEvents()
    first = time.perf_counter()-start
    frames = []
    def record(cpu, gpu, wall):
        frames.append((cpu, gpu, wall))
        label.setText(f'{wall:.2f} ms | {1000/max(wall, 0.001):.1f} fps | GPU {gpu}')
    view.frameReady.connect(record)
    orbit_start = time.perf_counter()
    yaw = view.camera.yaw
    def tick():
        elapsed = time.perf_counter()-orbit_start
        view.camera.yaw = yaw + min(elapsed/10, 1)*2*math.pi
        view.draw_frame()
        if elapsed >= 10:
            timer.stop()
            before = time.perf_counter()
            picked = view.renderer.pick(int(view.width()*view.devicePixelRatioF()/2), int(view.height()*view.devicePixelRatioF()/2))
            pick_ms = (time.perf_counter()-before)*1000
            def summary(col):
                values = [row[col] for row in frames if row[col] is not None]
                return dict(min=min(values), avg=sum(values)/len(values), max=max(values)) if values else None
            print(json.dumps(dict(model=str(args.model), adapter=view.renderer.adapter,
                load_s=loaded-start, build_s=view.build_seconds, upload_s=view.upload_seconds,
                first_picture_s=first, gpu_buffer_bytes=view.renderer.gpu_memory,
                attachment_bytes=view.width()*view.height()*view.devicePixelRatioF()**2*8,
                placements=len(view.packed.instances), prototypes=len(view.packed.bounds),
                visible_placements=int((view.packed.instances["info"][:, 2] == 0).sum()),
                triangles=len(view.packed.indices)//3, frames=len(frames), cpu_ms=summary(0),
                gpu_ms=summary(1), wall_ms=summary(2), pick_ms=pick_ms, picked=picked,
                logical_size=[view.width(), view.height()], scale=view.devicePixelRatioF()), indent=2), flush=True)
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(tick)
    if args.measure:
        timer.start(0)
    QTimer.singleShot(240000, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
