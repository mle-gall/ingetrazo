"""Bounded real-app new-document captures and Metal interaction checks.

Run via an external 60-second timeout, with INGETRAZO_WGPU=0 or 1:
  python scripts/wgpu_billboards_axes_verify.py OUTPUT gl|before|after --new-window
The main entry always launches with --new-window and exits after its captures.
"""
import os, sys, subprocess, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, QPointF, Qt
from PySide6.QtGui import QImage, QVector3D
from types import SimpleNamespace
import json
from PySide6.QtWidgets import QApplication
from views.main_window import MainWindow
out=Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
label=sys.argv[2]
old=MainWindow.__init__
def init(self,*args,**kwargs):
 old(self,*args,**kwargs)
 def close_home():
  for widget in QApplication.topLevelWidgets():
   if widget.windowTitle().startswith('Home'): widget.close()
 def capture(suffix):
  try:
   display=getattr(self._doc,'stand_in',None)
   if display is not None:
    display.draw_frame()
    w,h=int(display.width()*display.devicePixelRatioF()),int(display.height()*display.devicePixelRatioF())
    data=bytes(display.renderer.read_pixels())
    image=QImage(data,w,h,QImage.Format_RGBA8888).copy()
   else: image=self.viewport.grabFramebuffer()
   path=out / (label+'-'+suffix+'.png'); image.save(str(path))
   subprocess.run(['sips','-Z','1400',str(path)],timeout=15,stdout=subprocess.DEVNULL)
   print(str(path),flush=True)
   if suffix=='default':
    self.viewport.camera.yaw += 1.2
    self.viewport.update()
    if display is not None: display.update()
   else:
    if display is not None and label == 'after':
     verify(self, display)
    os._exit(0)
  except Exception:
   traceback.print_exc();os._exit(1)
 QTimer.singleShot(1000,close_home)
 QTimer.singleShot(3500,lambda:capture('default'))
 QTimer.singleShot(4500,lambda:capture('orbit'))
 QTimer.singleShot(20000,lambda:os._exit(2))
def verify(window, display):
 from tools.move import MoveTool
 from views.wgpu_inference import surface
 group=next(g for g in display.scene.groups if g.billboard)
 row=display.uid_rows[group.uid][0]
 center=QVector3D(*display._billboards.entries[0][0])+QVector3D(0,0,.85)
 def pick(point):
  display.draw_frame()
  pixel=display._world_to_pixel(point)
  assert display.pick_row(*pixel)==row, (pixel, display.pick_row(*pixel), row)
  return pixel
 pixel=pick(center)
 display.select_rows([row])
 assert group in display.scene.selection
 window.viewport.set_active_tool(MoveTool())
 display.tools.sync()
 event=SimpleNamespace(position=lambda:QPointF(*pixel), modifiers=lambda:Qt.NoModifier)
 display.last_snap=SimpleNamespace(point=center,kind='face')
 display.tools.click(event)
 delta=QVector3D(1.5,0,0)
 display.last_snap=SimpleNamespace(point=center+delta,kind='face')
 display.tools.hover(event)
 pick(center+delta)
 display.tools.click(event)
 pick(center+delta)
 if display._inference_future is not None:
  display._inference_future.result(timeout=10)
 display.draw_frame()
 eye=display.camera.eye()
 ray=(center+delta-eye).normalized()
 hit=surface(display.inference_index,row,eye,ray)
 assert hit is not None and (hit-center-delta).length()<1e-4
 window.viewport.view_tint={group.uid:(.2,.6,.9)}
 display.draw_frame()
 pick(center+delta)
 window.viewport.view_tint=None
 display.scene.begin_group_edit(group)
 display.set_scene(display.scene)
 pick(center+delta)
 display.scene.end_group_edit()
 display.set_scene(display.scene)
 pick(center+delta)
 (out/'interaction.json').write_text(json.dumps(dict(
  select=True,move_preview=True,move_commit=True,inference=True,
  tint=True,edit_context=True),indent=2))
 print('Select, move preview/commit, inference, tint, edit context: passed',flush=True)

MainWindow.__init__=init
import main
sys.argv=['main.py','--new-window']
main.main()
