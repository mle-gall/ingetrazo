"""Sheet dispatch and isolation contracts, independent of a Metal device."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from core.composition import MarcoVista
from core.saved_views import SavedView
from tests.test_composer_perspective import _composer

_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize('metal', [False, True])
def test_sheet_dispatch_and_override_restoration(metal):
    composer, host = _composer()
    calls = []
    def render(w, h, **kwargs):
        calls.append((w, h))
        return QImage(w, h, QImage.Format_RGB32)
    host._doc = SimpleNamespace(_renderer_wgpu=metal,
                               stand_in=SimpleNamespace(render_image=render))
    host.viewport.render_image = render if not metal else lambda *a, **k: pytest.fail('GL used')
    host.viewport.plano_style = 'lineas'
    frame = MarcoVista(w_mm=20, h_mm=10, style='tecnico')
    image = composer.render_frame(frame)
    assert (image.width(), image.height()) == calls[0] == frame.render_px(300)
    assert host.viewport.plano_style == 'lineas'
    composer.close()
    host.close()


def test_saved_frame_restores_hidden_camera_and_filter_on_error():
    from core.group import Group
    from core.mesh import Mesh
    composer, host = _composer()
    vp = host.viewport
    group = Group(Mesh())
    vp.scene.groups.append(group)
    saved = SavedView.capture('sheet', vp.scene, vp.camera)
    saved.hidden_objects = [group.uid]
    saved.two_point = True
    vp.scene.saved_views.append(saved)
    vp.scene._navigator_allowed = {'live'}
    vp.view_tint = {'live': (1., 0., 0.)}
    def fail():
        assert group.hidden
        assert vp.scene._navigator_allowed is None
        raise RuntimeError('capture failed')
    with pytest.raises(RuntimeError):
        composer._with_frame_camera(MarcoVista(view_key='scene:sheet'), fail)
    assert not group.hidden
    assert not vp.camera.two_point
    assert vp.scene._navigator_allowed == {'live'}
    assert vp.view_tint == {'live': (1., 0., 0.)}
    composer.close()
    host.close()


def test_offscreen_size_and_live_camera_unchanged(monkeypatch):
    import sys
    import views.wgpu_view as module
    from views.viewport import Viewport
    from core.scene import Scene
    from core.camera import OrbitCamera
    class Renderer:
        def __init__(self, handle, w, h, scale): self.size = w, h
        def set_style(self, payload): pass
        def set_camera(self, *args): pass
        def request_capture(self): pass
        def render(self, present): assert present is False
        def take_capture(self): return bytes(self.size[0]*self.size[1]*4)
    monkeypatch.setitem(sys.modules, 'ingetrazo_render', SimpleNamespace(Renderer=Renderer))
    monkeypatch.setattr(module, 'pack_scene', lambda *a: SimpleNamespace(instances=[1], upload=lambda r: None))
    source = SimpleNamespace(scene=Scene(), camera=OrbitCamera(), plano_style=None,
                             style_override=None, _horizon_ndc_y=lambda m: 2.)
    source._effective_style = lambda: Viewport._effective_style(source)
    view = module.WgpuView()
    view.source_viewport = source
    before = dict(source.camera.__dict__)
    image = view.render_image(123, 47)
    assert (image.width(), image.height()) == (123, 47)
    assert source.camera.__dict__ == before
    view.close()


def test_scene_recall_updates_metal_layers_camera_style_and_filter():
    from core.layers import Layer
    from core.scene import Scene
    from core.camera import OrbitCamera
    from core.style import Style
    from views.tray import ScenesPanel
    scene, camera = Scene(), OrbitCamera()
    layer = Layer(name='Detail')
    scene.layers.append(layer)
    layer.visible = False
    scene.display_style = Style(face_mode='wireframe')
    camera.distance = 42.
    view = SavedView.capture('Plan', scene, camera)
    layer.visible = True
    camera.distance = 1.
    scene.display_style = Style()
    scene._navigator_allowed = {'old'}
    calls = []
    viewport = SimpleNamespace(scene=scene, camera=camera, update=lambda: None,
                               view_tint=None, active_view_key='old')
    display = SimpleNamespace(set_scene=lambda s: calls.append(s), update=lambda: None)
    window = SimpleNamespace(viewport=viewport,
                             _doc=SimpleNamespace(_renderer_wgpu=True, stand_in=display),
                             statusBar=lambda: SimpleNamespace(showMessage=lambda *a: None))
    panel = SimpleNamespace(_window=window, _scene=lambda: scene, _touch=lambda: None)
    ScenesPanel._on_activate(panel, SimpleNamespace(data=lambda role: view))
    assert calls == [scene]
    assert camera.distance == 42.
    assert not layer.visible
    assert scene.display_style.face_mode == 'wireframe'
    assert scene._navigator_allowed is None
