"""Bounded native cap pixel test; run with a 120-second external timeout."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.sections-work/textures').resolve())
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path('.sections-work/settings').resolve()))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D
from core.scene import Scene
from core.section import SectionPlane
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from tests.test_section_fill import _box
app = QApplication([])
scene = Scene()
_box(scene.loose_mesh, -1, -1, -1, 2, 2, 2)
scene.section_planes = [SectionPlane(QVector3D(), QVector3D(1, 0, 0), active=True)]
scene.show_section_planes = False
gl = Viewport()
gl.scene = scene
view = WgpuView()
view.resize(600, 400)
view.set_scene(scene)
gl.camera = view.camera
view.source_viewport = gl
view.show()
app.processEvents()
view.draw_frame()
for mode in ('shaded', 'hidden_line', 'monochrome', 'xray'):
    scene.display_style.face_mode = mode
    scene.display_style.section_fill = True
    filled = view.render_image(600, 400)
    scene.display_style.section_fill = False
    hollow = view.render_image(600, 400)
    changed = bytes(filled.constBits()) != bytes(hollow.constBits())
    assert changed == (mode != 'xray'), (mode, changed)
print('native shaded, hidden-line, monochrome caps and X-ray suppression passed', flush=True)
view.close()
gl.close()
