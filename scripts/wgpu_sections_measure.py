"""Run with an external 240-second timeout; all writable caches stay local."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.sections-work/textures').resolve())
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path('.sections-work/settings').resolve()))
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.section import SectionPlane
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.wgpu_style import style_payload
app = QApplication([])
model, phase = Path(sys.argv[1]), sys.argv[2]
out = Path('docs/benchmarks/wgpu-sections-2026-11-09')
out.mkdir(parents=True, exist_ok=True)
scene = Scene()
load_into(scene, model)
gl = Viewport()
gl.scene = scene
gl.resize(800, 600)
metal = WgpuView()
metal.resize(800, 600)
metal.set_scene(scene)
gl.camera = metal.camera
metal.source_viewport = gl
metal.show()
app.processEvents()
metal.draw_frame()
scene.show_section_planes = False
result = {'load_average': os.getloadavg(), 'passes': {}}
for section in (False, True) if phase != 'before' else (False,):
    if section:
        lo, hi = scene.bounds()
        scene.section_planes = [SectionPlane(point=(lo+hi)*.5, normal=QVector3D(1,0,0), active=True)]
    for edges in (False, True):
        scene.display_style.edges = edges
        scene.display_style.profiles = edges
        metal.draw_frame()
        for _ in range(30):
            metal.renderer.render(False)
            time.sleep(.01)
        # Drain queued work so the ring cannot report the previous variant.
        metal.renderer.request_capture()
        metal.renderer.render(False)
        metal.renderer.take_capture()
        metal.renderer.render(False)
        key = f'section-{section}-edges-{edges}'
        result['passes'][key] = metal.renderer.last_timings()
        print(key, result['passes'][key], flush=True)
        if section and 'ride' not in model.stem:
            metal.renderer.request_capture()
            metal.renderer.render(False)
            from PySide6.QtGui import QImage
            w,h = int(metal.width()*metal.devicePixelRatioF()), int(metal.height()*metal.devicePixelRatioF())
            data = bytes(metal.renderer.take_capture())
            QImage(data,w,h,w*4,QImage.Format_RGBA8888).save(str(out/f'{model.stem}-{key}-metal.png'))
            gl.show()
            app.processEvents()
            gl.render_image(w,h,overlays=False).save(str(out/f'{model.stem}-{key}-gl.png'))
if phase != 'before':
    metal.renderer.request_capture()
    metal.renderer.render(False)
    interactive_before = bytes(metal.renderer.take_capture())
    memory_before = metal.renderer.gpu_memory
    start = time.perf_counter()
    image = metal.render_image(4961,3508) if 'ride' in model.stem else metal.render_image(600,400)
    result['sheet_seconds'] = time.perf_counter()-start
    result['sheet_size'] = [image.width(),image.height()]
    metal.renderer.request_capture()
    metal.renderer.render(False)
    assert bytes(metal.renderer.take_capture()) == interactive_before
    assert metal.renderer.gpu_memory == memory_before
    result['interactive_pixels_restored'] = True
    result['resident_bytes_unchanged'] = True
(out/f'{model.stem}-{phase}.json').write_text(json.dumps(result,indent=2))
print(result, flush=True)
metal.close()
gl.close()
