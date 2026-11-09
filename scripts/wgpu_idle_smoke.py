"""Bounded native smoke for the settled-camera ID repaint (run from the worktree)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtTest import QTest
from core.scene import Scene
from core.group import Group
from core.mesh import Mesh
from views.wgpu_view import WgpuView
app=QApplication([])
mesh=Mesh();mesh.add_face([QVector3D(0,0,0),QVector3D(2,0,0),QVector3D(0,2,0)])
v=WgpuView();v.resize(1000,700);v.set_scene(Scene(groups=[Group(mesh)]));v.show()
frames=[];v.frameReady.connect(lambda *args:frames.append(args))
failed=[]
def check():
 try:
  v.renderer.set_antialias(True)
  v.camera.yaw+=.01
  v.draw_frame()
  before=len(frames)
  QTest.qWait(250)
  assert len(frames)>before, 'no settled repaint'
  print('PASS: unchanged-camera repaint delivered automatically after navigation:',len(frames)-before,flush=True)
 except Exception as exc: failed.append(exc);print(repr(exc),flush=True)
 finally: v.close();app.quit()
QTimer.singleShot(500,check);QTimer.singleShot(5000,app.quit);app.exec()
if failed:raise SystemExit(1)
