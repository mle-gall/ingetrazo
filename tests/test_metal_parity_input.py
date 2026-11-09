"""P1: unshown Qt events, shared GL contracts, and capture state restoration."""
import math
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QVector3D, QMatrix4x4, QContextMenuEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.history import History
from tools.select import SelectTool
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.wgpu_inference import prepare

app = QApplication.instance() or QApplication([])


@pytest.fixture
def view():
    source = Viewport()
    source.scene = Scene()
    source.history = History(source.scene)
    source.flash_status = lambda *a: None
    source.notify_scene_changed = lambda: None
    source.active_tool = SelectTool()
    v = WgpuView()
    v.resize(800, 600)
    source.resize(800, 600)
    v.source_viewport = source
    v.camera = source.camera
    v.camera.target = QVector3D(1, 1, 0)
    v.camera.pitch = math.pi / 2 - .001
    v.camera.distance = 8
    v.camera.aspect = 800 / 600
    v.set_scene(source.scene)
    v.setAttribute(Qt.WA_DontShowOnScreen)
    v._upload = lambda: None
    yield v
    v.renderer = None
    v.close()
    source.close()


def face(view):
    f = view.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                                  QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    view.scene.version += 1
    view.set_scene(view.scene)
    view.inference_index = prepare(view.packed)
    view.pick_row = lambda *a: 0
    return f


def pixel(view, point):
    x, y = view._world_to_pixel(point)
    return QPoint(round(x), round(y))


def mouse_move(view, p):
    # QTest.mouseMove uses the OS cursor on macOS; send a genuine Qt move to
    # the unshown widget so tests never move Maxence's pointer.
    event = QMouseEvent(QMouseEvent.MouseMove, QPointF(p), QPointF(p),
                        Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(view, event)


def test_click_hover_modifiers(view):
    f = face(view)
    p = pixel(view, QVector3D(1, 1, 0))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, p)
    assert view.scene.selection == {f}
    QTest.mouseClick(view, Qt.LeftButton, Qt.ControlModifier, p)
    assert view.scene.selection == {f}
    QTest.mouseClick(view, Qt.LeftButton, Qt.ShiftModifier, p)
    assert not view.scene.selection
    QTest.mouseClick(view, Qt.LeftButton, Qt.ShiftModifier, p)
    assert view.scene.selection == {f}
    QTest.mouseClick(view, Qt.LeftButton, Qt.ControlModifier | Qt.ShiftModifier, p)
    assert not view.scene.selection
    mouse_move(view, p)
    assert view.tools._mesh_hover is None  # GL suppresses face hover
    edge = view.scene.edges[0]
    mouse_move(view, pixel(view, (edge.a + edge.b) * .5))
    assert view.tools._mesh_hover is edge


def test_box_occluded_and_loose(view):
    f = face(view)
    mesh = Mesh()
    mesh.add_face([QVector3D(0, 0, -1), QVector3D(2, 0, -1), QVector3D(0, 2, -1)])
    group = Group(mesh)
    view.scene.groups.append(group)
    view.scene.version += 1
    view.set_scene(view.scene)
    # Row picking sees only the front face; box selection must see the back group.
    view.pick_row = lambda *a: 0
    pts = [pixel(view, p) for p in f.vertices]
    lo = QPoint(min(p.x() for p in pts)-15, min(p.y() for p in pts)-15)
    hi = QPoint(max(p.x() for p in pts)+15, max(p.y() for p in pts)+15)
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, lo)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, hi)
    assert f in view.scene.selection and group in view.scene.selection
    assert all(e in view.scene.selection for e in view.scene.edges)
    mid = QPoint((lo.x()+hi.x())//2, hi.y())
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, lo)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, mid)
    assert f not in view.scene.selection
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, mid)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, lo)
    assert f in view.scene.selection


def fixed_world(view, point):
    # Isolate command events from inference, tested independently above.
    view.hover = lambda *a: setattr(view, 'last_snap', SimpleNamespace(
        point=QVector3D(*point), kind=None, context=None))


def test_section_place_move_toggle_undo(view):
    from tools.section import SectionPlaneTool
    from tools.move import MoveTool
    view.source_viewport.active_tool = SectionPlaneTool()
    fixed_world(view, (0, 0, 0))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(400, 300))
    plane, = view.scene.section_planes
    assert plane.active
    view.source_viewport.active_tool = SelectTool()
    view.tools.sync()
    frame = view.tools.section_plane_frame(plane)
    p = pixel(view, (frame[0] + frame[1]) * .5)
    assert view.tools.pick_section_plane(p.x(), p.y()) is plane
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, p)
    assert not plane.active
    view.source_viewport.history.undo()
    assert plane.active
    view.scene.select([plane])
    view.source_viewport.active_tool = MoveTool()
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(400, 300))
    fixed_world(view, (0, 0, 2))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(400, 300))
    assert plane.point.z() == 2
    view.source_viewport.history.undo()
    assert plane.point.z() == 0
    view.source_viewport.history.undo()
    assert not view.scene.section_planes


def test_copy_move_array_and_undo(view):
    from tools.move import MoveTool
    mesh = Mesh()
    mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    group = Group(mesh)
    group.xform = QMatrix4x4()
    view.scene.groups.append(group)
    view.scene.select([group])
    view.scene.version += 1
    view.set_scene(view.scene)
    view.source_viewport.active_tool = MoveTool()
    fixed_world(view, (0, 0, 0))
    QTest.mouseClick(view, Qt.LeftButton, Qt.ControlModifier, QPoint(400, 300))
    fixed_world(view, (2, 0, 0))
    QTest.mouseClick(view, Qt.LeftButton, Qt.ControlModifier, QPoint(420, 300))
    assert len(view.scene.groups) == 2
    assert group.xform.column(3).x() == 0
    QTest.keyClicks(view, '3x')
    QTest.keyClick(view, Qt.Key_Return)
    assert len(view.scene.groups) == 4
    assert sorted(g.xform.column(3).x() for g in view.scene.groups) == [0, 2, 4, 6]
    QTest.keyClicks(view, '/2')
    QTest.keyClick(view, Qt.Key_Return)
    assert sorted(g.xform.column(3).x() for g in view.scene.groups) == [0, 1, 2]
    view.source_viewport.history.undo()
    assert view.scene.groups == [group]


def test_context_group_and_locked_target(view):
    mesh = Mesh()
    mesh.add_face([QVector3D(), QVector3D(2, 0, 0), QVector3D(0, 2, 0)])
    group = Group(mesh)
    view.scene.groups.append(group)
    view.scene.version += 1
    view.set_scene(view.scene)
    view.pick_row = lambda *a: 0
    calls = []
    view.source_viewport.show_viewport_context_menu = lambda *a, **kw: calls.append(kw)
    event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(400, 300))
    view.contextMenuEvent(event)
    assert view.scene.selection == {group}
    group.locked = True
    view.scene.clear_selection()
    view.contextMenuEvent(event)
    assert not view.scene.selection
    assert calls[-1]['locked_group'] is group


def test_selection_marks_and_preview_bridge(view):
    from views.wgpu_overlay import rasterize, pixels
    f = face(view)
    view.scene.select([f])
    image = rasterize([], 800, 600, 1, view._draw_selection_marks)
    assert np.any(pixels(image)[3::4])
    count = len(view.packed.vertices)
    view.tools.set_suppressed_faces([f])
    assert view.suppressed_faces == (f,)
    assert not f.attrs.get('hidden')
    assert len(view.packed.vertices) < count
    view.tools.set_suppressed_faces([])
    assert len(view.packed.vertices) == count



@pytest.mark.parametrize('fail', [False, True])
def test_billboard_export_restores_world_and_schedules_overlays(view, fail):
    from core.group import make_billboard_group
    from views.wgpu_scene import INSTANCE
    from PySide6.QtGui import QImage
    from pathlib import Path
    texture = Path('resources/components/person_billboard.png').resolve()
    im = QImage(str(texture))
    view.scene.groups.append(make_billboard_group(str(texture), 1.75, 'Figure', im.width()/im.height()))
    view.scene.version += 1
    view.set_scene(view.scene)
    view._scene_dirty = False
    before = view.packed.instances['world'].copy()
    scheduled = []
    view.tools.draw_annotations = lambda p: scheduled.append(True)

    class Capture:
        def __init__(self):
            self.world = before.copy()
        def set_instance_world(self, ids, values):
            self.world[ids] = values.reshape(-1, 4, 4)
        def set_axes(self, *args):
            pass
        def set_section_geometry(self, *args):
            pass
        def render_image(self, width, height, vm, pm, style, data):
            rows = np.frombuffer(data, INSTANCE)
            np.testing.assert_allclose(rows['world'], self.world)
            assert not np.array_equal(self.world, before)
            if fail:
                raise RuntimeError('capture failed')
            return bytes(width * height * 4)

    view.renderer = Capture()
    if fail:
        with pytest.raises(RuntimeError, match='capture failed'):
            view.render_image(320, 240, overlays=True)
        assert not scheduled
    else:
        assert not view.render_image(320, 240, overlays=True).isNull()
        assert scheduled == [True]
    np.testing.assert_array_equal(view.renderer.world, before)
    np.testing.assert_array_equal(view.packed.instances['world'], before)


def test_loose_edge_without_resident_pixel(view):
    edge = view.scene.mesh.add_edge(QVector3D(), QVector3D(2, 0, 0))
    view.scene.version += 1
    view.set_scene(view.scene)
    # A thin edge need not cover the ID-buffer pixel within the pick tolerance.
    view.pick_row = lambda *args: None
    p = pixel(view, QVector3D(1, 0, 0)) + QPoint(0, 3)
    mouse_move(view, p)
    assert view.tools._mesh_hover is edge
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, p)
    assert view.scene.selection == {edge}


def test_hidden_reveal_invalidates_pack(view):
    from views.wgpu_view import _paint_key
    before = _paint_key(view.scene)
    view.scene.show_hidden_geometry = True
    assert _paint_key(view.scene) != before
    geometry = _paint_key(view.scene)
    view.scene.show_hidden_objects = True
    assert _paint_key(view.scene) != geometry


def test_texture_preview_owns_its_materials(view):
    from tools.texture_position import TexturePositionTool
    f = face(view)
    view.source_viewport.active_tool = TexturePositionTool()
    view.tools.sync()
    view.tools.set_suppressed_faces([f])
    assert not getattr(view, 'suppressed_faces', ())
    assert len(view.packed.vertices)


def test_guides_and_tool_overlay_without_labels(view):
    from core.guide import Guide
    from views.wgpu_overlay import rasterize, pixels
    from tools.walkthrough import WalkTool
    view.scene.guides.append(Guide(QVector3D(1, 1, 0)))
    view.source_viewport.active_tool = WalkTool()
    view.tools.sync()
    assert not view.scene.dimensions and not view.scene.text_labels
    calls = []
    view.tools.tool.draw_overlay = lambda vp, p: calls.append((vp.width(), vp.height()))
    image = rasterize([], 800, 600, 1, view.tools.draw_annotations)
    assert calls == [(800, 600)]
    assert np.any(pixels(image)[3::4])


def test_move_facade_reads_document_from_native_view(view):
    from tools.move import MoveTool
    from views.wgpu_tools import NativeTools
    mesh = Mesh()
    mesh.add_edge(QVector3D(), QVector3D(1, 0, 0))
    group = Group(mesh)
    group.xform = QMatrix4x4()
    view.scene.groups.append(group)
    view.scene.select([group])
    view.scene.version += 1
    view.set_scene(view.scene)
    old = view.source_viewport
    source = SimpleNamespace(active_tool=MoveTool(), history=old.history,
                             measurementChanged=SimpleNamespace(emit=lambda *a: None),
                             flash_status=lambda *a: None, notify_scene_changed=lambda: None)
    view.source_viewport = source
    native = NativeTools(view)
    event = SimpleNamespace(position=lambda: QPointF(400, 300), modifiers=lambda: Qt.NoModifier)
    try:
        for point in ((0, 0, 0), (2, 0, 0)):
            view.last_snap = SimpleNamespace(point=QVector3D(*point), kind=None)
            native.click(event)
        assert group.xform.column(3).x() == 2
        source.history.undo()
        assert group.xform.column(3).x() == 0
    finally:
        view.source_viewport = old
