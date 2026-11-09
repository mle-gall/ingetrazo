"""QImage parity with actual GL painter methods; no mapped widgets or GPU needed."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import copy
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D as V
from PySide6.QtWidgets import QApplication
from core.camera import OrbitCamera as Camera
from core.scene import Scene
from core.dimension import Dimension
from core.textlabel import TextLabel
from core.guide import Guide
from core.section import SectionPlane
from core.snap import SnapResult
from views.viewport import Viewport, _guide_vertices, shown_guides
from views.wgpu_overlay import draw_snap_indicator, pixels, rasterize, selection_rectangle
from views.wgpu_annotations import (
    AnnotationLayout, composite_annotations, draw_annotations, draw_tool_overlays,
    guide_segments,
)


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def painted(draw, size=(360, 100), dpr=1):
    image = QImage(int(size[0] * dpr), int(size[1] * dpr), QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        draw(painter)
    finally:
        painter.end()
    return image


def equal(a, b):
    assert a.size() == b.size()
    delta = np.abs(pixels(a).astype(int) - pixels(b).astype(int))
    assert delta.max(initial=0) <= 1


KINDS = ("endpoint origin component_origin on_edge on_axis intersection_edge "
         "intersection_face on_line extension from_point aligned tangent midpoint "
         "arc_midpoint on_face close reference through_point perp_face intersection "
         "center axis axis_inference none").split()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dpr", [1, 2])
def test_snap_matches_gl(kind, dpr):
    snap = SnapResult(kind=kind, point=V(48, 40, 0), color=(.16, .62, .36),
                      guide=(V(80, 40, 0), V(325, 40, 0)),
                      guide_color=(.86, .22, .27))
    snap.guides = [(V(80, 65, 0), V(325, 65, 0), (.2, .4, .78))]
    snap.axis = "z"
    snap.context = "component"
    project = lambda p: (p.x(), p.y())
    clip = lambda a, b: (a, b)
    reference = SimpleNamespace(_world_to_pixel=project, _clip_pixel_line=clip,
                                _SNAP_LABELS=Viewport._SNAP_LABELS)
    expected = painted(lambda p: Viewport._draw_snap_indicator(reference, p, snap), dpr=dpr)
    actual = painted(lambda p: draw_snap_indicator(p, snap, project, clip), dpr=dpr)
    equal(actual, expected)
    if kind in ("axis", "axis_inference"):
        assert not pixels(actual).any()


@pytest.mark.parametrize("style", ["window", "crossing", "zoom"])
@pytest.mark.parametrize("dpr", [1, 2])
def test_rectangle_matches_gl(style, dpr):
    a, b = (30, 20), (280, 80)
    if style == "crossing":
        a, b = b, a
    ns = SimpleNamespace(_box_active=True, _box_start=QPointF(*a), _box_cur=QPointF(*b),
                         BOX_DRAG_THRESHOLD_PX=6, _zoom_box_active=True,
                         _zoom_box_start=QPointF(*a), _zoom_box_cur=QPointF(*b))
    method = Viewport._draw_zoom_box if style == "zoom" else Viewport._draw_selection_box
    expected = painted(lambda p: method(ns, p), dpr=dpr)
    actual = rasterize([selection_rectangle(a, b, zoom=style == "zoom")], 360, 100, dpr)
    equal(actual, expected)


def fixture():
    scene = Scene()
    scene.dimensions = [Dimension(V(-2, 0, 0), V(2, 0, 0), V(0, -1, 0))]
    scene.text_labels = [TextLabel(V(0, 0, 0), V(-1, 0, 2), "Leader\nsecond line")]
    scene.guides = [Guide(V(0, 0, 1), V(1, 0, 0)),
                    Guide(V(-2, 0, 1), origin=V(-2, 0, 0))]
    scene.section_planes = [SectionPlane(V(0, 0, 0), V(0, 0, 1), active=False)]
    camera = Camera()
    camera.distance = 12
    return scene, camera


@pytest.mark.parametrize("size,dpr", [((640, 400), 1), ((1280, 800), 2),
                                     ((500, 700), 1), ((1000, 1400), 2)])
@pytest.mark.parametrize("only", [True, False])
def test_export_layout_matches_gl_at_output_aspect(size, dpr, only):
    scene, camera = fixture()
    old_aspect = camera.aspect
    # Reference uses a real (never shown) GL viewport's painter code at the
    # virtual sheet size. No GL context, render, or native window is requested.
    gl = Viewport()
    gl.scene = scene
    gl.camera = copy(camera)
    logical_height = size[1] * 640 / size[0]
    gl.resize(640, round(logical_height))
    gl.width = lambda: 640
    gl.height = lambda: logical_height
    gl.camera.aspect = 640 / logical_height
    gl._hover_entity = None
    gl._occluded_on_screen = lambda p: False
    gl._depth_snap = None
    gl._preview_groups = None
    def reference(p):
        p.scale(size[0] / 640 / dpr, size[0] / 640 / dpr)
        if not only:
            # GL guides are native world segments; paint their projection to
            # compare dash placement without asserting GPU AA/depth parity.
            from views.wgpu_annotations import draw_guide_lines
            draw_guide_lines(p, gl)
            for name in ("_draw_guides", "_draw_section_planes", "_draw_geo_surfaces",
                         "_draw_geo_paths", "_draw_geo_points"):
                getattr(gl, name)(p)
        gl._draw_dimensions(p)
        gl._draw_text_labels(p)
    expected = painted(reference, (size[0] / dpr, size[1] / dpr), dpr)
    blank = painted(lambda p: None, (size[0] / dpr, size[1] / dpr), dpr)
    actual = composite_annotations(blank, scene, camera, logical_size=(640, 400),
                                   annotations_only=only)
    equal(actual, expected)
    assert pixels(actual).sum() > 0
    assert not pixels(blank).any()
    assert camera.aspect == old_aspect
    equal(composite_annotations(actual, scene, camera, logical_size=(640, 400),
                                overlays=False), actual)
    gl.close()


def test_guide_world_dash_geometry_and_selection():
    scene, camera = fixture()
    scene.select([scene.guides[0]])
    segments, flags = guide_segments(scene, camera)
    coords, spans = _guide_vertices(shown_guides(scene), camera.distance * .03,
                                   scene.selection, centre=camera.target,
                                   reach=camera.distance * 15, eye=camera.eye())
    np.testing.assert_array_equal(segments.reshape(-1), np.asarray(coords))
    assert flags[:spans[0][1] // 2].all()
    assert not flags[spans[0][1] // 2:].any()
    # The world-space dash occupies half each period.
    assert np.isclose(np.linalg.norm(segments[0, 1] - segments[0, 0]) /
                      np.linalg.norm(segments[1, 0] - segments[0, 0]), .5, atol=3e-5)


@pytest.mark.parametrize("tool_name", ["walk", "flip"])
def test_tool_overlay_on_empty_annotation_document(tool_name):
    scene, camera = fixture()
    scene.dimensions = []
    scene.text_labels = []
    layout = AnnotationLayout(scene, camera, (360, 100))
    if tool_name == "walk":
        from tools.walkthrough import WalkTool
        tool = WalkTool()
        tool._anchor_px = QPointF(180, 50)
    else:
        from tools.flip import FlipTool
        from core.mesh import Mesh
        from core.group import Group
        mesh = Mesh()
        mesh.add_face([V(-1, -1, 0), V(1, -1, 0), V(0, 1, 1)])
        group = Group(mesh)
        scene.groups.append(group)
        scene.select([group])
        tool = FlipTool()
    layout.tool = tool
    expected = painted(lambda p: tool.draw_overlay(layout, p))
    actual = painted(lambda p: draw_tool_overlays(p, layout, labels=False))
    equal(actual, expected)
    assert pixels(actual).sum() > 0


@pytest.mark.parametrize("label", ["axis", "reference", "plane", "inference", "linear"])
def test_lock_labels_match_gl(label):
    ns = SimpleNamespace(reference_mode=None, reference_edge=None, axis_lock=None,
                         last_snap=None, linear_inference_mode="all", height=lambda: 100)
    ns.tool = ns.active_tool = SimpleNamespace(plane_lock=None)
    method = None
    if label == "axis":
        ns.axis_lock = "x"
        method = Viewport._draw_axis_lock_label
    elif label == "reference":
        ns.reference_mode, ns.reference_edge = "parallel", object()
        method = Viewport._draw_reference_label
    elif label == "plane":
        ns.tool.plane_lock = "y"
        method = Viewport._draw_plane_lock_label
    elif label == "inference":
        ns.last_snap = SnapResult(kind="axis", point=V(), color=(.2, .4, .78), axis="z")
        method = Viewport._draw_inference_label
    else:
        ns.linear_inference_mode = "off"
        method = Viewport._draw_linear_mode_label
    equal(painted(lambda p: draw_tool_overlays(p, ns)),
          painted(lambda p: method(ns, p)))


def test_capture_occlusion_callback_and_painter_state():
    scene, camera = fixture()
    layout = AnnotationLayout(scene, camera, (360, 100), occluded=lambda p: p.x() > 0)
    assert layout._project_samples([V(-1, 0, 0), V(1, 0, 0)])[1][1] is False
    def paint(p):
        before = (p.pen(), p.brush(), p.font(), p.transform())
        draw_annotations(p, scene, camera, (360, 100), annotations_only=True)
        assert before == (p.pen(), p.brush(), p.font(), p.transform())
    painted(paint)
