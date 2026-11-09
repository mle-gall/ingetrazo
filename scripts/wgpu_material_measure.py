"""Bounded Metal-only material diagnostic; invoke with a 290-second outer timeout."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.look-tmp/textures').resolve())
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
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
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
failed = []
def measure():
    try:
        view.draw_frame()
        result = dict(prototypes=len(view.packed.bounds), vertices=len(view.packed.vertices),
                      material_bytes=view.packed.materials.nbytes, resident_bytes=view.renderer.gpu_memory,
                      size=[int(view.width()*view.devicePixelRatioF()), int(view.height()*view.devicePixelRatioF())], frames={})
        for aa in (False, True):
            view.renderer.set_antialias(aa)
            samples=[]
            for k in range(45):
                cpu,gpu=view.renderer.render(False)
                if k>=10: samples.append([cpu,gpu or 0.])
                time.sleep(.12)
            result['frames'][str(aa)]=dict(zip(('cpu_ms','gpu_ms'),np.median(samples,axis=0).tolist()))
        picks=[]
        for k in range(5):
            start=time.perf_counter()
            view.renderer.pick(1000,700)
            picks.append((time.perf_counter()-start)*1000)
        result['pick_ms']=picks
        (out/(Path(sys.argv[1]).stem+'-metal-only.json')).write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    except Exception as exc:
        failed.append(exc)
        import traceback
        traceback.print_exc()
    finally:
        view.close()
        app.quit()
QTimer.singleShot(1500,measure)
QTimer.singleShot(240000,app.quit)
app.exec()
if failed: raise SystemExit(1)
