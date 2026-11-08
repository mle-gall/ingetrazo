"""Bounded native ride overlay proof with captured pixels and frame timings."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["INGETRAZO_RUST"] = "1"
os.environ.setdefault("INGETRAZO_TEXTURE_CACHE", str(Path(".r2-tmp/textures").resolve()))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_view import WgpuView
from views.wgpu_overlay import Primitive, axes, snap_glyph

out = Path("docs/benchmarks/wgpu-r2-2026-11-08")
app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
view.overlay_primitives = [
    Primitive("rectangle", ((10, 10), (250, 65)), "#ff0000", fill="#ff0000"),
    Primitive("text", ((25, 42),), "#ffffff", text="R2 Metal overlay proof"),
    Primitive("polyline", ((300, 100), (460, 240), (620, 150))),
    Primitive("rectangle", ((280, 80), (650, 260)), "#ffff00"),
    snap_glyph((460, 240), "midpoint"),
    *axes((80, 610), ((1, 0), (-.5, -.5), (0, -1))),
]
view.show()
rows = []
def tick():
    view.draw_frame()
    rows.append(view.overlay_ms)
    if len(rows) == 120:
        timer.stop()
        QTimer.singleShot(500, finish)
def finish():
    view.renderer.request_capture()
    view.draw_frame()
    data = bytes(view.renderer.take_capture())
    ratio = view.devicePixelRatioF()
    image = QImage(data, int(view.width()*ratio), int(view.height()*ratio), QImage.Format_RGBA8888)
    image.save(str(out / "overlay-surface.png"))
    color = image.pixelColor(int(20*ratio), int(20*ratio))
    result = dict(capture="wgpu surface readback after overlay, before present", scale=view.devicePixelRatioF(), capture_scale=ratio,
                  badge_pixel=color.getRgb(), overlay_visible=color.red()>240 and color.green()<15,
                  placements=len(view.packed.uids), frames=len(rows),
                  overlay_raster_upload_ms=dict(min=min(rows), avg=sum(rows)/len(rows), max=max(rows)))
    (out / "overlay.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    view.close()
    app.quit()
timer = QTimer()
timer.timeout.connect(tick)
timer.start(16)
QTimer.singleShot(240000, app.quit)
app.exec()
