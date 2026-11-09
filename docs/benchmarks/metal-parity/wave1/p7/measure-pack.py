"""Repeated pack time/allocation/RSS, keeping the previous pack alive.

Invoke with MODEL OUTPUT; externally bound to 300 seconds. No renderer/window.
"""
import json
import resource
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[5]))
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.wgpu_scene import pack_scene
app=QApplication([])
s=Scene();load_into(s,Path(sys.argv[1]));p=None;results=[]
for i in range(2):
 start=time.perf_counter();p=pack_scene(s)
 results.append(dict(seconds=time.perf_counter()-start,
   rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,timings=p.timings,
   vertices=p.vertices.nbytes,materials=p.materials.nbytes,
   hidden_vertices=int(p.hidden_commands['count'].sum()+p.hidden_edge_commands['count'].sum()),
   textures=sum(map(len,p.textures[3])),
   uptime=subprocess.check_output(['uptime'],text=True,timeout=5).strip()))
 Path(sys.argv[2]).write_text(json.dumps(results,indent=2))
 print(results[-1],flush=True)
