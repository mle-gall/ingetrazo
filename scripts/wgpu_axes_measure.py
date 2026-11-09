"""Paired axes-off/on cost on one resident scene; externally bound to 240 s.

  python scripts/wgpu_axes_measure.py MODEL OUTPUT --new-window
The native window is hidden immediately after initialization. Timings use
paced offscreen frames, with no capture/readback in the measurement loop.
"""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.look-tmp/textures').resolve())
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_view import WgpuView
from views.wgpu_axes import axes_state
from views.wgpu_style import style_payload
app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
view.show()
app.processEvents()
view.draw_frame()
if '--capture' in sys.argv:
    from views.viewport import Viewport
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import Qt
    reference = Viewport()
    reference.scene, reference.camera = scene, view.camera
    view.source_viewport = reference
    view.draw_frame()
    w, h = int(view.width()*view.devicePixelRatioF()), int(view.height()*view.devicePixelRatioF())
    data = bytes(view.renderer.read_pixels())
    native = QImage(data,w,h,QImage.Format_RGBA8888).copy().scaledToWidth(1400, Qt.SmoothTransformation)
    folder = Path(sys.argv[2]).parent
    native.save(str(folder/'space_asbuilt_ride-wgpu.png'))
    gl = QImage(str(folder/'space_asbuilt_ride-gl.png'))
    if not gl.isNull():
        pair = QImage(gl.width()+native.width(), native.height(), QImage.Format_RGB32)
        painter = QPainter(pair)
        painter.drawImage(0,0,gl)
        painter.drawImage(gl.width(),0,native)
        painter.end()
        pair.scaledToWidth(1400, Qt.SmoothTransformation).save(str(folder/'space_asbuilt_ride-comparison.png'))
    view.source_viewport = None
    reference.close()
view.hide()
if view._inference_future is not None:
    view._inference_future.result(timeout=30)
frame, spacing, _ = axes_state(scene, view.camera)
result = {'adapter': view.renderer.adapter, 'size': [2000, 1400],
          'warmup': 3, 'samples_per_block': 10, 'pace_seconds': .08,
          'load_average_start': os.getloadavg(), 'modes': {}}
payload = style_payload(scene)
payload.update(ambient_occlusion=False, edges=True, profiles=False)
view.renderer.set_style(payload)
for aa in (True, False):
    view.renderer.set_antialias(aa)
    blocks = []
    # Reverse the order in alternating pairs to reduce drift bias.
    for pair in range(8):
        for enabled in ((False, True) if pair % 2 == 0 else (True, False)):
            view.renderer.set_axes(frame, spacing, enabled)
            samples = []
            for i in range(13):
                begin = time.perf_counter()
                view.renderer.render(False)
                wall = (time.perf_counter()-begin)*1000
                cpu, gpu, acquire, *_ = view.renderer.last_timings()
                if i >= 3:
                    samples.append([cpu, gpu, wall, *view.renderer.frame_stage_timings()])
                time.sleep(.08)
            blocks.append({'pair': pair, 'axes': enabled, 'samples': samples,
                           'median': np.median(samples, axis=0).tolist()})
    off = np.median([b['median'] for b in blocks if not b['axes']], axis=0)
    on = np.median([b['median'] for b in blocks if b['axes']], axis=0)
    result['modes'][str(aa)] = {'blocks': blocks, 'off_ms': off.tolist(), 'on_ms': on.tolist(),
                              'delta_ms': (on-off).tolist(), 'columns': ['cpu', 'gpu', 'wall', 'poll', 'acquire', 'encode', 'submit', 'present']}
result['load_average_end'] = os.getloadavg()
Path(sys.argv[2]).write_text(json.dumps(result, indent=2))
print(json.dumps({k: {n:v[n] for n in ('off_ms','on_ms','delta_ms')} for k,v in result['modes'].items()}), flush=True)
view.close()
