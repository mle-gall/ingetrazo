"""Native tools retain the document command and cancellation contracts."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from tools.base import ToolContext
from tools.rotate import RotateTool
from core.camera import OrbitCamera
from tests.test_wgpu_mesh_tools import harness, click, event, geometry


def prepare(tool):
    scene, history, native, updates = harness(tool)
    native.camera = OrbitCamera()
    native.pick_face_any = lambda *args: (None, None)
    return scene, history, native, updates


def test_rotate_loose_matches_direct_command_and_cancel():
    def setup():
        scene, history, native, updates = prepare(RotateTool())
        face = scene.mesh.add_face([QVector3D(), QVector3D(2, 0, 0),
                                    QVector3D(0, 2, 0)])
        scene.select([face])
        native.update()
        return scene, history, native
    scene, history, native = setup()
    reference, ref_history, direct = setup()
    before = geometry(scene.mesh)
    for point in [(0, 0, 0), (2, 0, 0), (0, 2, 0)]:
        click(native, point)
        native.tool.on_release(native)
        ctx = ToolContext(direct, QVector3D(*point), QPointF(), Qt.NoModifier, None)
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
        direct.tool.on_release(direct)
    assert type(history.undo_stack[-1]) is type(ref_history.undo_stack[-1])
    assert geometry(scene.mesh) == geometry(reference.mesh)
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives

from tools.scale import ScaleTool


def test_scale_handles_numeric_commit_and_cancel():
    scene, history, native, _ = prepare(ScaleTool())
    face = scene.mesh.add_face([QVector3D(), QVector3D(2, 0, 0),
                                QVector3D(0, 2, 0)])
    scene.select([face])
    native.tool.on_activate(native)
    native.update()
    before = geometry(scene.mesh)
    native.mesh_feedback()
    assert any(p.kind == 'rectangle' for p in native.view.overlay_primitives)
    grip = next(g for g in native.tool._grips if len(g.mask) == 2)
    native.tool._grab(native, grip, (0, 0))
    native.tool._apply_preview(native, (2., 2., 1.))
    native.cancel()
    assert geometry(scene.mesh) == before
    assert not native.view.overlay_primitives
    native.tool.on_activate(native)
    grip = next(g for g in native.tool._grips if len(g.mask) == 2)
    native.tool._grab(native, grip, (0, 0))
    assert native.tool.on_value(native, 2.)
    after = geometry(scene.mesh)
    assert after != before
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after

from tools.offset import OffsetTool


def test_offset_numeric_undo_and_cancel():
    scene, history, native, _ = prepare(OffsetTool())
    face = scene.mesh.add_face([QVector3D(), QVector3D(4, 0, 0),
                                QVector3D(4, 4, 0), QVector3D(0, 4, 0)])
    native.pick_face = lambda *args: face
    native.pick_edge = lambda *args: None
    native._pixel_to_ray = lambda *args: (QVector3D(2, 1, 10), QVector3D(0, 0, -1))
    native.update()
    before = geometry(scene.mesh)
    click(native, (2, 1, 0))
    native.tool.on_value(native, .5)
    assert history.undo_stack
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives

from tools.circle import CircleTool, PolygonTool
from tools.arc import ArcTool


@pytest.mark.parametrize('tool_type,points', [
    (CircleTool, [(0, 0, 0), (2, 0, 0)]),
    (PolygonTool, [(0, 0, 0), (2, 0, 0)]),
    (ArcTool, [(0, 0, 0), (2, 0, 0), (1, 1, 0)]),
])
def test_radial_commands_match_direct(tool_type, points):
    scene, history, native, _ = prepare(tool_type())
    reference, ref_history, direct, _ = prepare(tool_type())
    for point in points:
        click(native, point)
        ctx = ToolContext(direct, QVector3D(*point), QPointF(), Qt.NoModifier, None)
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
    assert history.undo_stack
    assert type(history.undo_stack[-1]) is type(ref_history.undo_stack[-1])
    assert geometry(scene.mesh) == geometry(reference.mesh)
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives
