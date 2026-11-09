"""Same-resident-scene A/B of base versus integrated hover, no mapped window.

Invoke with MODEL OUTPUT BASE_COMMIT; externally bound to 360 seconds.
The base hover function is compiled from that commit; native pack and P6 index
are shared to isolate the integration cost from load/pack and GPU warmup.
"""
import ast
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D, QColor
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.history import History
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.wgpu_inference import prepare
from tools.tape import TapeMeasureTool
import ingetrazo_render
app=QApplication([])
scene=Scene();load_into(scene,Path(sys.argv[1]))
v=WgpuView();v.resize(1000,700);v.setAttribute(Qt.WA_DontShowOnScreen)
v._prepare_inference=lambda:None;v.set_scene(scene)
source=Viewport();source.scene=scene;source.history=History(scene)
source.camera=v.camera;source.active_tool=TapeMeasureTool();source.flash_status=lambda *a:None
v.source_viewport=source
v.inference_index=prepare(v.packed,scene)
native=ingetrazo_render.Renderer(int(v.winId()),1000,700,1.)
v.packed.upload(native);v._scene_dirty=False
class Offscreen:
 def render(self):return native.render(False)
 def __getattr__(self,name):return getattr(native,name)
v.renderer=Offscreen();v.devicePixelRatioF=lambda:1.
v.draw_frame();v.draw_frame()
code=subprocess.check_output(['git','show',sys.argv[3]+':views/wgpu_view.py'],text=True,timeout=10)
cls=next(n for n in ast.parse(code).body if isinstance(n,ast.ClassDef) and n.name=='WgpuView')
fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='hover')
ns=dict(time=time,np=np,Qt=Qt,QVector3D=QVector3D,QColor=QColor)
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<base-hover>','exec'),ns)
result={'base':sys.argv[3],'uptime':subprocess.check_output(['uptime'],text=True,timeout=5).strip(),
 'method':'same packed ride / same resident GPU / same P6 index; base hover versus integrated hover; Tape tool; no OS input'}
points=[(x,y) for y in (150,300,450,600) for x in range(100,901,100)]
for label,hover in [('before',ns['hover']),('after',WgpuView.hover)]:
 for x,y in points[:6]:hover(v,x,y)
 samples=[]
 for x,y in points*2:
  start=time.perf_counter();hover(v,x,y);samples.append((time.perf_counter()-start)*1000)
 result[label]={'p50_ms':float(np.percentile(samples,50)),'p95_ms':float(np.percentile(samples,95)),'samples_ms':samples}
Path(sys.argv[2]).write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if k not in ('before','after')})
v.renderer=None;v.close();source.close()
