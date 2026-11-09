"""Paired perf-round-3 measurements; run each invocation with a 240s timeout."""
import json
import os
from pathlib import Path
import statistics
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if os.environ.get('PERF_BASELINE'):
    sys.path.insert(0, str(root / '.baseline-work'))
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(root / '.tmp-work/textures')
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root / '.tmp-work/settings'))
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.section import SectionPlane
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.wgpu_style import style_payload

app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
source = Viewport()
source.scene = scene
source.camera = view.camera
view.source_viewport = source
view.show()
app.processEvents()
view.draw_frame()
width = int(view.width()*view.devicePixelRatioF())
height = int(view.height()*view.devicePixelRatioF())
results = {}
out = root / 'docs/benchmarks/perf-round-3-2026-11-09' / sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
for section, aa, ao, profiles in [(False, a, o, True) for a in (False, True) for o in (False, True)] + [(False, False, False, False), (True, False, False, True), (True, True, True, True)]:
    if section:
        lo, hi = scene.bounds()
        scene.section_planes = [SectionPlane(point=(lo+hi)*.5, normal=QVector3D(1, 0, 0), active=True)]
        scene.show_section_planes = False
    scene.display_style.profiles = profiles
    view.draw_frame()
    payload = style_payload(scene)
    payload.update(ambient_occlusion=ao, ao_resolution=2.)
    view.renderer.set_style(payload)
    view.renderer.set_antialias(aa)
    samples = []
    for i in range(14):
        view.renderer.request_capture()
        view.renderer.render(False)
        pixels = bytes(view.renderer.take_capture())
        view.renderer.render(False)
        if i >= 4:
            samples.append(view.renderer.last_timings()[3])
    key = f'section={section},msaa={aa},ao={ao},profiles={profiles}'
    results[key] = dict(load_average=os.getloadavg(), size=[width, height], counters=view.renderer.last_timings()[4], passes={k: statistics.median(s[k] for s in samples) if samples[0][k] is not None else None for k in samples[0]})
    print(key, results[key], flush=True)
    QImage(pixels, width, height, width*4, QImage.Format_RGBA8888).save(str(out / (key + '.png')))
scene.section_planes = []
view.draw_frame()
results['pick'] = []
for i in range(5):
    view.camera.yaw += .001
    view.draw_frame()
    start = time.perf_counter()
    view.renderer.pick(width//2, height//2)
    cold = (time.perf_counter()-start)*1000
    id_gpu = view.renderer.last_timings()[3].get("id")
    view.renderer.render(False)
    view.renderer.render(False)
    view.renderer.request_capture()
    view.renderer.render(False)
    view.renderer.take_capture()
    start = time.perf_counter()
    view.renderer.pick(width//2, height//2)
    results['pick'].append(dict(cold_ms=cold, id_gpu_ms=id_gpu, settled_ms=(time.perf_counter()-start)*1000, load_average=os.getloadavg()))
(out / 'timings.json').write_text(json.dumps(results, indent=2))
view.close()
source.close()
