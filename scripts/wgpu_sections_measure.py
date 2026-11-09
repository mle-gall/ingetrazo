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
metal.resize(1000, 700) if 'ride' in model.stem else metal.resize(800, 600)
metal.set_scene(scene)
gl.camera = metal.camera
metal.source_viewport = gl
metal.show()
app.processEvents()
metal.draw_frame()
scene.show_section_planes = False
result = {'load_average': os.getloadavg(), 'physical_size': [int(metal.width()*metal.devicePixelRatioF()), int(metal.height()*metal.devicePixelRatioF())], 'passes': {}}
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
        samples = []
        for _ in range(12):
            metal.renderer.request_capture()
            metal.renderer.render(False)
            metal.renderer.take_capture()
            metal.renderer.render(False)
            samples.append(metal.renderer.last_timings()[3])
        import statistics
        result.setdefault('samples', {})[key] = samples
        result['passes'][key] = {name: statistics.median(s[name] for s in samples) if samples[0][name] is not None else None for name in samples[0]}
        result.setdefault('loads', {})[key] = os.getloadavg()
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
    if 'ride' not in model.stem:
        original = bytes(image.constBits())
        old_fill = scene.display_style.section_fill
        scene.display_style.section_fill = False
        without_fill = metal.render_image(600, 400)
        scene.display_style.section_fill = old_fill
        result['native_cap_changes_pixels'] = original != bytes(without_fill.constBits())
        result['cap_triangles'] = len(metal._section_geometry_cache[2])
        hidden = [g.hidden for g in scene.groups]
        try:
            for g in scene.groups:
                g.hidden = True
            filtered = metal.render_image(600, 400)
            assert original != bytes(filtered.constBits())
        finally:
            for g, value in zip(scene.groups, hidden):
                g.hidden = value
        old_tint = getattr(gl, 'view_tint', None)
        try:
            gl.view_tint = {uid: (1., 0., 0.) for uid in metal.packed.uids}
            tinted = metal.render_image(600, 400)
            assert original != bytes(tinted.constBits())
        finally:
            gl.view_tint = old_tint
        restored = metal.render_image(600, 400)
        assert original == bytes(restored.constBits())
        result['native_visibility_tint_restored'] = True
    metal.renderer.request_capture()
    metal.renderer.render(False)
    assert bytes(metal.renderer.take_capture()) == interactive_before
    assert metal.renderer.gpu_memory == memory_before
    result['interactive_pixels_restored'] = True
    result['resident_bytes_unchanged'] = True
    if 'ride' in model.stem:
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWidget
        from core.saved_views import SavedView
        from core.composition import MarcoVista
        from core.outliner import fit_scale
        from views.composer import ComposerWindow
        saved = SavedView.capture('R3b', scene, gl.camera)
        scene.saved_views.append(saved)
        host = QWidget()
        host.viewport = gl
        host._doc = SimpleNamespace(_renderer_wgpu=True, stand_in=metal)
        composer = ComposerWindow(host)
        frame = MarcoVista(w_mm=420., h_mm=297., view_key='scene:R3b', style='tecnico', paper_bg=True)
        frame.scale_n = fit_scale(scene, saved, 420., 297., fill=.90)
        start = time.perf_counter()
        image = composer.render_frame(frame)
        result['composer'] = dict(seconds=time.perf_counter()-start, size=[image.width(), image.height()], scale=frame.scale_n, style=frame.style, dpi=300)
        image.save(str(out/f'{model.stem}-composer-metal.png'))
(out/f'{model.stem}-{phase}-bis.json').write_text(json.dumps(result,indent=2))
print({k:v for k,v in result.items() if k not in ('samples', 'passes')}, flush=True)
metal.close()
gl.close()
