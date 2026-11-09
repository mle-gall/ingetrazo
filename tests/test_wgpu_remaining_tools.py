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

from tools.paint import PaintTool


def test_paint_face_history_restores_material():
    scene, history, native, _ = prepare(PaintTool())
    face = scene.mesh.add_face([QVector3D(), QVector3D(2, 0, 0),
                                QVector3D(0, 2, 0)])
    native.pick_face_any = lambda *args: (face, None)
    native.pick_face_placement = lambda *args: (face, None)
    native._pixel_to_ray = lambda *args: (QVector3D(1, 1, 10), QVector3D(0, 0, -1))
    native.update()
    before = dict(face.attrs)
    click(native, (1, 1, 0))
    assert history.undo_stack
    assert tuple(face.attrs.get('color')) == PaintTool.current_color
    history.undo()
    native.update()
    assert face.attrs == before
    history.redo()
    native.update()
    assert tuple(face.attrs.get('color')) == PaintTool.current_color
    native.cancel()
    assert not native.view.overlay_primitives

from tools.dimension import DimensionTool
from tools.text import TextTool


@pytest.mark.parametrize('tool_type,points,collection', [
    (DimensionTool, [(0, 0, 0), (2, 0, 0), (1, 1, 0)], 'dimensions'),
    (TextTool, [(0, 0, 0), (2, 0, 0)], 'text_labels'),
])
def test_annotation_history_and_cancel(tool_type, points, collection, monkeypatch):
    monkeypatch.setattr('views.prompts.get_multiline_text', lambda *a: ('Label', True))
    scene, history, native, _ = prepare(tool_type())
    native.window = lambda: None
    for point in points:
        click(native, point)
    assert len(getattr(scene, collection)) == 1
    history.undo()
    native.update()
    assert not getattr(scene, collection)
    history.redo()
    native.update()
    assert len(getattr(scene, collection)) == 1
    native.cancel()
    assert not native.view.overlay_primitives

def test_annotations_rasterize_without_gl(monkeypatch):
    from core.dimension import Dimension
    from core.textlabel import TextLabel
    from views.wgpu_overlay import rasterize, pixels
    scene, _, native, _ = prepare(DimensionTool())
    scene.dimensions.append(Dimension(QVector3D(10, 10, 0), QVector3D(70, 10, 0),
                                      QVector3D(0, 20, 0)))
    scene.text_labels.append(TextLabel(QVector3D(10, 10, 0), QVector3D(30, 40, 0), 'Label'))
    native._is_occluded = lambda p: False
    image = rasterize([], 100, 100, 1., native.draw_annotations)
    assert pixels(image).reshape(-1, 4)[:, 3].any()

from tools.followme import FollowMeTool


def test_followme_preselected_path_undo():
    scene, history, native, _ = prepare(FollowMeTool())
    face = scene.mesh.add_face([QVector3D(), QVector3D(1, 0, 0),
                                QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    edge = scene.mesh.add_edge(QVector3D(), QVector3D(0, 0, 3))
    scene.select([edge])
    native.pick_face = lambda *a: face
    native.tool.on_activate(native)
    native.update()
    before = geometry(scene.mesh)
    click(native, (0, 0, 0))
    assert history.undo_stack
    after = geometry(scene.mesh)
    assert after != before
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives
