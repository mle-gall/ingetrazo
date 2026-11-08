"""Bounded native smoke check for display APIs and a sibling overlay on macOS.

The red badge uses its own native view; it never paints into the Metal layer.
A window capture checks native compositing rather than QWidget.render().
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget
from core.mesh import Mesh
from core.group import Group
from core.scene import Scene
from views.wgpu_view import WgpuView


class Badge(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(10, 10, 50, 30, QColor(255, 0, 0))


def main():
    app = QApplication([])
    window = QWidget()
    window.resize(400, 300)
    view = WgpuView(window)
    view.setGeometry(0, 0, 400, 300)
    mesh = Mesh()
    mesh.add_face([QVector3D(-1, -1, 0), QVector3D(1, -1, 0), QVector3D(0, 1, 0)])
    group = Group(mesh)
    view.set_scene(Scene(groups=[group]))
    badge = Badge(window)
    badge.setGeometry(0, 0, 100, 60)
    window.show()
    view.show()
    badge.show()
    badge.raise_()

    def verify():
        result = {}
        try:
            for style in ('shaded', 'xray', 'hidden_line', 'monochrome', 'wireframe'):
                view.renderer.set_style(style)
                view.set_highlight([group.uid], group.uid)
                view.draw_frame()
            view.renderer.set_style('shaded')
            view.draw_frame()
            result['rectangle_ids'] = view.pick_rect(0, 0, 400, 300)
            assert result['rectangle_ids'] == [group.uid]
            pixmap = window.screen().grabWindow(int(window.winId()))
            pixmap.save('.spike-results/overlay.png')
            image = pixmap.toImage()
            ratio = pixmap.devicePixelRatio()
            color = image.pixelColor(int(20*ratio), int(20*ratio))
            result['badge_pixel'] = color.getRgb()
            result['overlay_visible'] = color.red() > 240 and color.green() < 15
            result['native_styles_and_pick'] = True
        except Exception as error:
            result['error'] = str(error)
        print(json.dumps(result), flush=True)
        view.renderer = None
        window.close()
        app.quit()
    QTimer.singleShot(2000, verify)
    QTimer.singleShot(10000, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
