"""Display-only native Metal widget, isolated from the production tool API."""
import time
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QWidget
from core.camera import OrbitCamera
from views.wgpu_scene import pack_scene


class WgpuView(QWidget):
    frameReady = Signal(float, object, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        for attr in (Qt.WA_NativeWindow, Qt.WA_PaintOnScreen, Qt.WA_NoSystemBackground):
            self.setAttribute(attr)
        self.camera = OrbitCamera()
        self.renderer = None
        self.packed = None
        self._scene_dirty = False
        self.last = None
        self.build_seconds = self.upload_seconds = 0.

    def paintEngine(self):
        return None

    def set_scene(self, scene):
        start = time.perf_counter()
        self.packed = pack_scene(scene)
        self._scene_dirty = True
        self.build_seconds = time.perf_counter()-start
        lo, hi = self.packed.world_bounds
        self.camera.target = QVector3D(*((lo+hi)/2))
        self.camera.distance = max(float(np.linalg.norm(hi-lo))*1.4, 1.)
        self._upload()

    def _upload(self):
        if self.packed is None or not self.isVisible():
            return
        import ingetrazo_render
        start = time.perf_counter()
        if self.renderer is None:
            self.renderer = ingetrazo_render.Renderer(int(self.winId()), self.width(), self.height(), self.devicePixelRatioF())
        if len(self.packed.instances):
            self.packed.upload(self.renderer)
        self.upload_seconds = time.perf_counter()-start
        self._scene_dirty = False
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.renderer is None or self._scene_dirty:
            self._upload()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.renderer is not None:
            self.renderer.resize(self.width(), self.height(), self.devicePixelRatioF())
        self.update()

    def draw_frame(self):
        if self.renderer is None or not len(self.packed.instances):
            return None
        start = time.perf_counter()
        self.camera.aspect = self.width()/max(1, self.height())
        self.renderer.set_camera(self.camera.view_matrix().data(), self.camera.projection_matrix().data())
        cpu, gpu = self.renderer.render()
        wall = (time.perf_counter()-start)*1000
        self.frameReady.emit(cpu, gpu, wall)
        return cpu, gpu, wall

    def paintEvent(self, event):
        self.draw_frame()

    def mousePressEvent(self, event):
        self.last = event.position()
        self.press = event.position()

    def mouseMoveEvent(self, event):
        if self.last is None:
            return
        delta = event.position()-self.last
        self.last = event.position()
        if event.buttons() & Qt.RightButton:
            self.camera.pan(delta.x(), delta.y(), self.height())
        else:
            self.camera.orbit(delta.x(), delta.y(), self.height())
        self.update()

    def mouseReleaseEvent(self, event):
        if self.renderer is not None and (event.position()-self.press).manhattanLength() < 3:
            scale = self.devicePixelRatioF()
            index = self.renderer.pick(int(event.position().x()*scale), int(event.position().y()*scale))
            print('pick', self.packed.uids[index] if index >= 0 else None, flush=True)
        self.last = None

    def wheelEvent(self, event):
        self.camera.zoom(event.angleDelta().y()/120)
        self.update()

    def closeEvent(self, event):
        self.renderer = None
        super().closeEvent(event)
