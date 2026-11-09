"""Bounded native API smoke for resident growth and prototype replacement."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D, QMatrix4x4
from core.mesh import Mesh
from core.group import Group
from core.scene import Scene
from views.wgpu_view import WgpuView
app = QApplication([])
mesh = Mesh()
mesh.add_face([QVector3D(0,0,0), QVector3D(1,0,0), QVector3D(0,1,0)])
scene = Scene(groups=[Group(mesh)])
view = WgpuView()
view.resize(400,300)
view.set_scene(scene)
view.show()
app.processEvents()
view.set_highlight([scene.groups[0].uid])
for i in range(3):
    group = Group(mesh)
    group.xform = QMatrix4x4()
    group.xform.translate(i*.1, 0, 0)
    scene.groups.append(group)
    scene.version += 1
    view.set_scene(scene)
    view.draw_frame()
for height in (1, 2, 3, 4):
    new = Mesh()
    new.add_edge(QVector3D(), QVector3D(1,1,height))
    scene.groups.append(Group(new))
    scene.version += 1
    view.set_scene(scene)
    view.draw_frame()
mesh.move_vertex(mesh.vertices[0], QVector3D(0,0,.1))
scene.version += 1
view.set_scene(scene)
view.draw_frame()
scene.groups.pop(0)
scene.version += 1
view.set_scene(scene)
view.draw_frame()
view.close()
print('Native growth, prototype insertion/replacement and removal completed')
