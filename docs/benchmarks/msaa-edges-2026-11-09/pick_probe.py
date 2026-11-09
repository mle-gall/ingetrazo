"""Paced native performance matrix; run with an external 290-second timeout."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path.cwd()))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.look-tmp/textures').resolve())
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_view import WgpuView
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
if view._inference_future is not None:
    view._inference_future.result()

import json
# Drain prior color work through a capture before timing ID-only requests.
view.renderer.read_pixels()
key=view._last_camera
result={'load_start':os.getloadavg(),'samples':[]}
for i in range(10):
    v=list(key[0]);v[12]+=(i+1)*.01
    view.renderer.set_camera(v,key[1])
    start=time.perf_counter()
    picked=view.renderer.pick(1000,700)
    result['samples'].append((time.perf_counter()-start)*1000)
result['load_end']=os.getloadavg()
Path(sys.argv[2]).write_text(json.dumps(result,indent=2))
print(result,flush=True)
view.close()
