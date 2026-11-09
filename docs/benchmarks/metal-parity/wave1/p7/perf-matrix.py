"""Paced native performance matrix; run with an external 400-second timeout."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.look-tmp/textures').resolve())
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from core.scene import Scene
from formats.igz import load_into
if os.environ.get('P2_BASELINE'):
    import importlib.util
    spec=importlib.util.spec_from_file_location('ingetrazo_render',str(Path('.look-tmp/baseline-render.so').resolve()))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.modules['ingetrazo_render']=module
from views.wgpu_view import WgpuView
from views.wgpu_style import style_payload
app = QApplication([])
scene = Scene()
load_into(scene, Path(sys.argv[1]))
view = WgpuView()
view.resize(1000, 700)
view.set_scene(scene)
view.setAttribute(Qt.WA_DontShowOnScreen)
view._prepare_inference = lambda: None
import ingetrazo_render
view.renderer = ingetrazo_render.Renderer(int(view.winId()), 1000, 700, 1.)
view.packed.upload(view.renderer)
view._scene_dirty = False
native_renderer = view.renderer
class OffscreenRenderer:
    def render(self, present=False):
        return native_renderer.render(False)
    def __getattr__(self, name):
        return getattr(native_renderer, name)
view.renderer = OffscreenRenderer()
view.devicePixelRatioF = lambda: 1.
view.draw_frame()
if view._inference_future is not None:
    view._inference_future.result()
import subprocess
uptime = subprocess.check_output(['uptime'], timeout=5, text=True).strip()
result = {'uptime': uptime, 'method': 'original frame matrix on unshown native host, render(False)', 'size': [int(view.width()*view.devicePixelRatioF()), int(view.height()*view.devicePixelRatioF())],
          'adapter': view.renderer.adapter, 'frames': {}, 'warmup': 10, 'samples': 20, 'sleep_seconds': .12, 'load_average_start': os.getloadavg(), 'contended': True, 'pass_notes': {'ao_inputs': 'copy not timed separately', 'profile_classification': 'included in edge_quads', 'id': 'included in faces when refreshed; explicit pick pass not timestamped', 'present': 'CPU-only, offscreen frames do not present', 'antialias': 'faces and resolve; edges included when AO off', 'antialias_edges': 'edges and resolve after AO'}}
payload = style_payload(scene, scale=view.devicePixelRatioF())
for opacity, aa, ao, edges, profiles in [(opacity, *config) for config in ([(aa, ao, True, False) for aa in (False, True) for ao in ('off','half','full')] + [(False,'off',False,False),(False,'off',True,True)]) for opacity in (False, True)]:
    payload.update(material_opacity=opacity, ambient_occlusion=ao != 'off', ao_resolution=1 if ao == 'full' else 2,
                   edges=edges, profiles=profiles)
    view.renderer.set_style(payload)
    view.renderer.set_edges(edges)
    view.renderer.set_antialias(aa)
    samples = []
    passes = []
    counters = []
    load_start = os.getloadavg()
    for i in range(30):
        start = time.perf_counter()
        cpu, gpu = view.renderer.render(False)
        if i >= 10:
            samples.append([cpu,gpu,(time.perf_counter()-start)*1000])
            passes.append(view.renderer.last_timings()[3])
            counters.append(view.renderer.last_timings()[4])
        time.sleep(.12)
    result['frames'][f'opacity={opacity},msaa={aa},ao={ao},edges={edges},profiles={profiles}'] = {'median': np.median(samples,axis=0).tolist(), 'samples': samples, 'gpu_pass_medians_ms': {k: (float(np.median([p[k] for p in passes])) if passes[0][k] is not None else None) for k in passes[0]}, 'gpu_pass_samples_ms': passes, 'counters': counters, 'load_average_start': load_start, 'load_average_end': os.getloadavg()}
view.renderer.set_antialias(False)
payload.update(ambient_occlusion=False, edges=True, profiles=False)
view.renderer.set_style(payload)
for label in ('cold','settled'):
    samples=[]
    for i in range(5):
        view.camera.yaw += .01
        view.draw_frame()
        if label == 'settled':
            time.sleep(.08)
            view.draw_frame()
            time.sleep(.12)
        start=time.perf_counter()
        view.renderer.pick(1000,700)
        samples.append((time.perf_counter()-start)*1000)
    result[label+'_pick_ms']=samples
import hashlib
view.renderer.set_antialias(False)
hashes = []
for opacity in (False, True):
    payload.update(material_opacity=opacity)
    pixels = bytes(view.renderer.render_image(1000,700,
        tuple(view.camera.view_matrix().data()), tuple(view.camera.projection_matrix().data()), payload))
    hashes.append(hashlib.sha256(pixels).hexdigest())
result['opaque_capture_sha256'] = hashes
result['opaque_capture_identical'] = hashes[0] == hashes[1]
out=Path(sys.argv[2])
out.parent.mkdir(parents=True,exist_ok=True)
result['load_average_end'] = os.getloadavg()
out.write_text(json.dumps(result,indent=2))
print(json.dumps({'uptime':uptime,'opaque_capture_identical':result['opaque_capture_identical']}),flush=True)
view.close()
