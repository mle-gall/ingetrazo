"""Run in a worktree-local, externally bounded child; source models are read-only."""
import os
import sys
import time
import json
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.spike-results/textures').resolve())
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path('.spike-results/settings').resolve()))
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QImage, QPainter
from core.scene import Scene
from core.saved_views import SavedView
from core.composition import MarcoVista
from core.outliner import fit_scale
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.composer import ComposerWindow

app = QApplication([])
source = Path(sys.argv[1])
only = sys.argv[2] if len(sys.argv) > 2 else None
out = Path('docs/benchmarks/wgpu-r3b-2026-11-09')
out.mkdir(parents=True, exist_ok=True)
scene = Scene()
load_into(scene, source)
print('loaded', flush=True)
gl = Viewport()
gl.scene = scene
gl.resize(800, 600)
lo, hi = scene.bounds()
gl.camera.target = (lo + hi) * .5
gl.camera.distance = max((hi-lo).length()*1.4, 1.)
saved = SavedView.capture('R3b', scene, gl.camera)
scene.saved_views.append(saved)
if only != 'metal':
    print('initializing GL', flush=True)
    gl.show()
    app.processEvents()
    print('GL initialized', flush=True)
metal = WgpuView()
metal.source_viewport = gl
host = QWidget()
host.viewport = gl
host._doc = SimpleNamespace(_renderer_wgpu=False, stand_in=metal)
composer = ComposerWindow(host)
# A3 landscape view at 300 dpi; smaller comparison sheets use 100x70 mm.
ride = 'ride' in source.stem
w, h = (420., 297.) if ride else (100., 70.)
frame = MarcoVista(w_mm=w, h_mm=h, view_key='scene:R3b', style='tecnico', paper_bg=True)
frame.scale_n = fit_scale(scene, saved, w, h, fill=.90)
images, timings = [], {}
for name in ([only] if only else ('gl', 'metal')):
    host._doc._renderer_wgpu = name == 'metal'
    print('rendering', name, flush=True)
    start = time.perf_counter()
    image = composer.render_frame(frame)
    timings[name] = time.perf_counter()-start
    if image is None or image.isNull(): raise RuntimeError(name+' returned no image')
    images.append(image)
    image.save(str(out / (source.stem+'-'+name+'.png')))
    print(name, timings[name], image.size(), flush=True)
if only:
    (out / (source.stem+'-'+only+'.json')).write_text(json.dumps(dict(seconds=timings, size=[images[0].width(), images[0].height()], dpi=300, scale=frame.scale_n, style=frame.style), indent=2))
    print('complete', flush=True)
    sys.exit(0)
left, right = images
pair = QImage(left.width()*2, left.height(), QImage.Format_RGB32)
painter = QPainter(pair)
painter.drawImage(0, 0, left)
painter.drawImage(left.width(), 0, right)
painter.end()
pair.save(str(out / (source.stem+'-comparison.png')))
(out / (source.stem+'.json')).write_text(json.dumps(dict(seconds=timings, size=[left.width(), left.height()], dpi=300, scale=frame.scale_n, style=frame.style), indent=2))
print('complete', flush=True)
# Do not process auto-render timers after this synchronous capture.
metal.close()
gl.close()
