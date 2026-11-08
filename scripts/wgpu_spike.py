"""Bounded, reproducible resident-scene orbit measurement on a native Qt view."""
import argparse
import json
import math
import os
import resource
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
    parser.add_argument('--interval', type=int, default=16)
    parser.add_argument('--no-edges', action='store_true')
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--inventory-only', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    window = QMainWindow()
    view = WgpuView()
    window.setCentralWidget(view)
    label = QLabel('Preparing resident scene')
    window.statusBar().addWidget(label)
    window.resize(1000, 700)
    cpu_start = time.process_time()
    start = time.perf_counter()
    scene = Scene()
    load_into(scene, args.model)
    loaded = time.perf_counter()
    print('loaded', loaded-start, flush=True)
    if args.inventory_only:
        from core.group import iter_placements
        from core.mesh import DeferredMesh
        groups = [g for root in scene.groups for g, _ in iter_placements(root)]
        meshes = {id(g.mesh): g.mesh for g in groups}
        counts = {}
        for key, mesh in meshes.items():
            src = mesh.__dict__.get('_deferred_source')
            counts[key] = ((len(src['pos']), len(src['counts']), len(src['edges']))
                           if src else (len(mesh.vertices), len(mesh.faces), len(mesh.edges)))
        print(json.dumps(dict(groups=len(groups), prototypes=len(meshes),
            raw_pos_placements=sum(counts[id(g.mesh)][0] > 0 for g in groups),
            raw_face_placements=sum(counts[id(g.mesh)][1] > 0 for g in groups),
            raw_edge_placements=sum(counts[id(g.mesh)][2] > 0 for g in groups),
            empty_meshes=sum(c == (0, 0, 0) for c in counts.values()),
            deferred=sum(type(m) is DeferredMesh for m in meshes.values())), indent=2))
        return
    view.set_scene(scene)
    window.show()
    app.processEvents()
    first = time.perf_counter()-start
    startup_cpu = time.process_time()-cpu_start
    view.renderer.set_edges(not args.no_edges)
    frames = []
    def record(cpu, gpu, wall):
        frames.append((cpu, gpu, wall, view.renderer.last_timings()[2]))
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
                triangles=int(view.packed.commands["count"].sum())//3,
                edges=not args.no_edges, samples=1, interval_ms=args.interval, startup_cpu_s=startup_cpu,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                acquire_ms=summary(3), frames=len(frames), cpu_ms=summary(0),
                gpu_ms=summary(1), wall_ms=summary(2), pick_ms=pick_ms, picked=picked,
                logical_size=[view.width(), view.height()], scale=view.devicePixelRatioF()), indent=2), flush=True)
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(tick)
    if args.measure:
        timer.start(args.interval)
    QTimer.singleShot(240000, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
