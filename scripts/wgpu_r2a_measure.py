"""Bounded native interaction measurements, excluding geometry load from hover."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_view import WgpuView

app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
view.show()
view.renderer.set_msaa("--msaa" in sys.argv)
frames = []

def measure():
    result = view.draw_frame()
    if result:
        frames.append(result)
    if view.inference_index is None or len(frames) < 20:
        return
    timer.stop()
    points = []
    for y in range(50, 651, 50):
        for x in range(50, 951, 50):
            if view.pick_row(x, y) is not None:
                points.append((x, y))
    hovers, snaps = [], []
    for x, y in points[:100]:
        answer = view.hover(x, y)
        hovers.append(view.hover_ms)
        snaps.append(None if answer is None else answer.kind)
    click = []
    click_gpu_complete = []
    for x, y in points[:20]:
        start = time.perf_counter()
        view.select_rows([view.pick_row(x, y)])
        click.append((time.perf_counter()-start)*1000)
        view.draw_frame()
        # A subsequent ID read waits for the submitted scene/highlight pass.
        # This bounds GPU completion, not OS compositor presentation.
        view.pick_row(x, y)
        click_gpu_complete.append((time.perf_counter()-start)*1000)
    start = time.perf_counter()
    rows = view.rect_rows(0, 0, 1000, 700)
    view.select_rows(rows)
    box_ms = (time.perf_counter()-start)*1000
    # Search outside the timed interval for a rectangle close to 1,000 IDs.
    low, high = 0., 1000.
    for _ in range(12):
        right = (low+high)/2
        candidate = view.rect_rows(0, 0, right, 700)
        if len(candidate) < 1000:
            low = right
        else:
            high = right
    view.scene.clear_selection()
    view.sync_selection()
    start = time.perf_counter()
    thousand = view.rect_rows(0, 0, high, 700)
    view.select_rows(thousand)
    thousand_ms = (time.perf_counter()-start)*1000
    view.draw_frame()
    view.pick_row(500, 350)
    thousand_gpu_complete_ms = (time.perf_counter()-start)*1000
    result = dict(click_gpu_complete_ms=click_gpu_complete,
                  thousand_gpu_complete_ms=thousand_gpu_complete_ms, thousand_box_count=len(thousand), thousand_box_ms=thousand_ms, placements=len(view.packed.uids), hover_ms=hovers, snap_kinds=snaps,
                  click_to_buffer_ms=click, box_count=len(rows), box_to_buffer_ms=box_ms,
                  frame_cpu_gpu_wall_ms=frames, msaa_samples=4 if "--msaa" in sys.argv else 1)
    path = Path('docs/benchmarks/wgpu-r2a-2026-11-08') / ('interaction-msaa.json' if '--msaa' in sys.argv else 'interaction.json')
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    view.close()
    app.quit()

timer = QTimer()
timer.timeout.connect(measure)
timer.start(33)
QTimer.singleShot(240000, app.quit)
app.exec()
