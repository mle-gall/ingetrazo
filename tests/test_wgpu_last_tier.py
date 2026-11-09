"""Shared commands must give identical geometry through native dispatch."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from tools.base import ToolContext
from tests.test_wgpu_mesh_tools import click, geometry
from tests.test_wgpu_remaining_tools import prepare
from tools.rotated_rectangle import RotatedRectangleTool
from tools.arc import ThreePointArcTool, CenterArcTool, PieTool

@pytest.mark.parametrize('tool_type,points', [
    (RotatedRectangleTool, [(0, 0, 0), (2, 0, 0), (2, 2, 0)]),
    (ThreePointArcTool, [(0, 0, 0), (1, 1, 0), (2, 0, 0)]),
    (CenterArcTool, [(0, 0, 0), (2, 0, 0), (0, 2, 0)]),
    (PieTool, [(0, 0, 0), (2, 0, 0), (0, 2, 0)]),
])
def test_last_tier_drawing(tool_type, points):
    scene, history, native, _ = prepare(tool_type())
    reference, ref_history, direct, _ = prepare(tool_type())
    for vp in (native, direct):
        vp.pick_face_placement = lambda *a: (None, None)
        vp.width = lambda: 1000
        vp.height = lambda: 700
    for point in points:
        click(native, point)
        ctx = ToolContext(direct, QVector3D(*point), QPointF(), Qt.NoModifier, type('Snap', (), {'kind': 'endpoint', 'context': None})())
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
    assert history.undo_stack
    assert type(history.undo_stack[-1]) is type(ref_history.undo_stack[-1])
    assert geometry(scene.mesh) == geometry(reference.mesh)
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    assert not scene.mesh.faces and not scene.mesh.edges
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives

from tools.freehand import FreehandTool
from types import SimpleNamespace

def test_freehand_stroke_commit_and_escape():
    scene, history, native, _ = prepare(FreehandTool())
    reference, _, direct, _ = prepare(FreehandTool())
    points = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 0, 0)]
    for i, point in enumerate(points):
        event = SimpleNamespace(position=lambda: QPointF(*point[:2]),
                                modifiers=lambda: Qt.NoModifier)
        native.view.last_snap = SimpleNamespace(point=QVector3D(*point), kind=None)
        ctx = ToolContext(direct, QVector3D(*point), event.position(), Qt.NoModifier, None)
        if i == 0:
            native.click(event)
            direct.tool.on_click(ctx)
        else:
            native.hover(event)
            direct.tool.on_hover(ctx)
    native.tool.on_release(native)
    direct.tool.on_release(direct)
    assert geometry(scene.mesh) == geometry(reference.mesh)
    assert history.undo_stack
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    assert not scene.mesh.edges
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    click(native, (0, 0, 0))
    native.cancel()
    native.tool.on_release(native)
    assert geometry(scene.mesh) == after

from tools.solid_tools import (OuterShellTool, UnionTool, SubtractTool,
                               TrimTool, IntersectTool, SplitTool)
from tests.test_solid_tools import _pair, _box, RED
from core import solids

@pytest.mark.parametrize('tool_type', [OuterShellTool, UnionTool, SubtractTool,
                                      TrimTool, IntersectTool, SplitTool])
def test_solid_click_results_and_undo(tool_type, monkeypatch):
    def setup():
        scene, history, vp, updates = prepare(tool_type())
        a, b = _pair()
        untouched = _box(10, 10, 10, 11, 11, 11, RED)
        scene.groups.extend([a, b, untouched])
        scene.version += 1
        vp.window = lambda: None
        vp.update()
        return scene, history, vp, updates, a, b, untouched
    scene, history, native, updates, a, b, untouched = setup()
    reference, _, direct, _, ra, rb, _ = setup()
    import views.wgpu_updates as update_module
    original_pack = update_module.pack_scene
    baked_meshes = []
    def record_pack(scene):
        baked_meshes.extend(g.mesh for g in scene.groups)
        return original_pack(scene)
    monkeypatch.setattr(update_module, 'pack_scene', record_pack)
    for group, ref in [(a, ra), (b, rb)]:
        native.pick_group = lambda *args: group
        direct.pick_group = lambda *args: ref
        click(native, (0, 0, 0))
        direct.tool.on_click(ToolContext(direct, QVector3D(), QPointF(), Qt.NoModifier, None))
    def volumes(scene):
        return sorted(round(solids.solid_volume(g), 6) for g in scene.groups)
    assert history.undo_stack
    assert volumes(scene) == volumes(reference)
    after = volumes(scene)
    assert untouched in scene.groups
    assert untouched.mesh not in baked_meshes
    assert baked_meshes
    history.undo()
    native.update()
    assert scene.groups == [a, b, untouched]
    history.redo()
    native.update()
    assert volumes(scene) == after
    native.cancel()
    assert native.tool.first is None

from tools.walkthrough import PositionCameraTool, LookAroundTool, WalkTool, FirstPersonTool

@pytest.mark.parametrize('tool_type', [PositionCameraTool, LookAroundTool, WalkTool, FirstPersonTool])
@pytest.mark.parametrize('mods', [Qt.NoModifier, Qt.ControlModifier, Qt.ShiftModifier, Qt.AltModifier])
def test_camera_shared_gestures(tool_type, mods):
    _, history, native, _ = prepare(tool_type())
    _, _, direct, _ = prepare(tool_type())
    for vp in (native, direct):
        vp.width = lambda: 1000
        vp.height = lambda: 700
        vp.ray_distance = lambda *a: None
        vp.window = lambda: None
        vp.tool._viewport = vp
        if tool_type is PositionCameraTool:
            vp.tool.place(vp, QVector3D(2, 3, 0))
        elif tool_type is LookAroundTool:
            vp.tool.on_click(ToolContext(vp, QVector3D(), QPointF(100, 100), mods, None))
            vp.tool.on_hover(ToolContext(vp, QVector3D(), QPointF(200, 150), mods, None))
        elif tool_type is WalkTool:
            vp.tool.step(vp, 50, 80, .1, mods)
        else:
            vp.tool.on_look(vp, 50, -20)
            vp.tool.step(vp, {Qt.Key_W, Qt.Key_D}, .1, mods)
    assert (native.camera.eye()-direct.camera.eye()).length() < 1e-6
    assert (native.camera.forward()-direct.camera.forward()).length() < 1e-6
    assert not history.undo_stack
    native.cancel()
    assert not native.view.overlay_primitives

from tools.protractor import ProtractorTool
from tools.geopath import GeoPathTool
from tools.change_axes import ChangeAxesTool
from tools.flip import FlipTool
from tools.fillet import FilletTool
from tests.test_fillet import box, edge_at

@pytest.mark.parametrize('tool_type', [ProtractorTool, GeoPathTool, ChangeAxesTool, FlipTool, FilletTool])
def test_editing_commands_and_cancel(tool_type):
    def setup():
        scene, history, vp, updates = prepare(tool_type())
        vp.window = lambda: None
        vp.ground_elevation = lambda *a: None
        vp.pick_face_placement = lambda *a: (None, None)
        vp.width = lambda: 1000
        vp.height = lambda: 700
        vp.view._world_to_pixel = lambda p: (p.x()*100, p.y()*100)
        if tool_type in (ChangeAxesTool, FlipTool):
            group = _box(0, 0, 0, 2, 2, 2, RED)
            scene.groups.append(group)
            scene.select([group])
            vp.tool.target = group
        if tool_type is FilletTool:
            for face in box().faces:
                scene.mesh.add_face(face.vertices)
            edge = edge_at(scene.mesh, (0, 0, 1), (2, 0, 1))
            vp._hover_edge = edge
            vp.pick_visible_edge = lambda *a: edge
            vp.tool._show_panel = lambda *a: None
            FilletTool.radius = .1
        vp.update()
        return scene, history, vp
    scene, history, native = setup()
    reference, _, direct = setup()
    points = ([(0, 0, 0), (2, 0, 0), (0, 2, 0)]
              if tool_type is not FilletTool else [(1, 0, 1), (1, .25, 1)])
    if tool_type is FlipTool:
        for vp in (native, direct):
            vp.tool.on_key(vp, Qt.Key_Right, Qt.NoModifier)
        points = [(0, 0, 0)]
    for point in points:
        click(native, point)
        ctx = ToolContext(direct, QVector3D(*point), QPointF(), Qt.NoModifier, None)
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
        if tool_type is ProtractorTool:
            native.tool.on_release(native)
            direct.tool.on_release(direct)
    if tool_type is GeoPathTool:
        for vp in (native, direct):
            vp.tool.on_double_click(ToolContext(vp, QVector3D(), QPointF(), Qt.NoModifier, None))
    def state(scene):
        return (geometry(scene.mesh), [geometry(g.mesh) for g in scene.groups],
                [(g.point.toTuple(), g.direction.toTuple()) for g in scene.guides],
                [[p.toTuple() for p in path.points] for path in scene.geo_paths])
    assert history.undo_stack
    assert state(scene) == state(reference)
    after = state(scene)
    history.undo()
    native.update()
    history.redo()
    native.update()
    assert state(scene) == after
    native.cancel()
    assert not native.view.overlay_primitives

def test_first_person_claims_shortcuts_and_timer_stops_on_focus_loss():
    from views.viewport import Viewport
    from views.wgpu_view import WgpuView
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent, QFocusEvent
    from tests.test_wgpu_mesh_tools import app
    source = Viewport()
    view = WgpuView()
    view.source_viewport = source
    view.camera = source.camera
    view.set_scene(source.scene)
    source.set_active_tool(FirstPersonTool())
    view.tools.sync()
    override = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_W, Qt.NoModifier)
    app.sendEvent(view, override)
    assert override.isAccepted()
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_W, Qt.NoModifier))
    tool = source.active_tool
    assert tool._timer.parent() is view
    assert tool._timer.isActive()
    assert tool._viewport is view.tools
    view.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert not tool.held and not tool._timer.isActive()
    view.close()
    source.close()

def test_committed_protractor_guide_rasterizes():
    from views.wgpu_overlay import rasterize
    scene, _, native, _ = prepare(ProtractorTool())
    native.width = lambda: 1000
    native.height = lambda: 700
    for point in [(0, 0, 0), (2, 0, 0), (0, 2, 0)]:
        click(native, point)
        native.tool.on_release(native)
    assert scene.guides
    image = rasterize([], 1000, 700, 1., native.draw_annotations)
    assert not image.isNull()
