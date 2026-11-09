"""Painter-only Metal annotations and the P1 integration contract.

Live: call draw_annotations(painter, scene, camera, (width, height),
occluded=tools._is_occluded) from rasterize's annotations callback. Schedule
this for guides/section widgets as well as dimensions/text, even in an otherwise
empty document. Then call draw_tool_overlays(painter, tools), independently of
document annotation presence. Draw snap feedback with wgpu_overlay.
draw_snap_indicator(painter, snap, layout._world_to_pixel,
layout._clip_pixel_line), where layout is the AnnotationLayout returned by
draw_annotations. Append selection_rectangle(start, end, zoom=False) after
the input drag threshold; retain unsorted start/end coordinates.

Export: after native capture, call composite_annotations(image, scene, camera,
logical_size=(live_width, live_height), annotations_only=False). It returns a
new image. Set overlays=False to leave it untouched. Camera is copied and its
aspect is set to the OUTPUT aspect, so sheet frames do not project through the
live widget. Uniform output_width/logical_width scaling keeps fonts/arrows
undistorted on differently shaped sheets; logical height follows output aspect.
Pass an occluded(world_point)->bool callback ONLY if valid for that capture
camera (never a stale live pick buffer). Default is visible, explicitly.

Document guide dashes reuse GL's world-space spacing/reach and colors; guide
points use GL's [14,10] pen. The overlay has NO depth attachment: guide lines
cannot match GL depth occlusion. Dimensions/leaders support the optional CPU
occlusion callback. P2 can move guide segments to a depth-tested native pass.
Live tools keep their own draw_overlay hook (Walk crosshair, Flip planes —
the reference Flip tool draws planes, not arrows). Export excludes these and
lock/snap/selection feedback. annotations_only excludes guides/section/geodata.

Only painter-safe GL methods are bound below, never a QWidget or GL context.
This shares annotation layout/localization rather than duplicating those rules.
"""
from copy import copy

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QVector3D

from views.viewport import Viewport, _guide_vertices, shown_guides


class AnnotationLayout:
    """Isolated scene/camera projection for a logical annotation canvas."""

    # Explicit allowlist: no accidental delegation into live widget geometry.
    _world_to_pixel = Viewport._world_to_pixel
    _clip_pixel_line = Viewport._clip_pixel_line
    _clip_segment_front = Viewport._clip_segment_front
    _draw_occluded_segment = Viewport._draw_occluded_segment
    _draw_dimensions = Viewport._draw_dimensions
    _draw_text_labels = Viewport._draw_text_labels
    _draw_guides = Viewport._draw_guides
    _draw_section_planes = Viewport._draw_section_planes
    section_plane_frame = Viewport.section_plane_frame
    _draw_geo_surfaces = Viewport._draw_geo_surfaces
    _draw_geo_paths = Viewport._draw_geo_paths
    _draw_geo_points = Viewport._draw_geo_points
    _draw_geo_path_label = Viewport._draw_geo_path_label
    ground_height = Viewport.ground_height
    drape = Viewport.drape
    _text_block_x = staticmethod(Viewport._text_block_x)
    _format_dim_value = staticmethod(Viewport._format_dim_value)
    _OCCLUSION_STEP_PX = Viewport._OCCLUSION_STEP_PX
    _OCCLUSION_MAX_SAMPLES = Viewport._OCCLUSION_MAX_SAMPLES
    _OCCLUSION_SPLIT = Viewport._OCCLUSION_SPLIT
    _OCCLUSION_ROUNDS = Viewport._OCCLUSION_ROUNDS

    def __init__(self, scene, camera, logical_size, *, occluded=None, hover=None):
        self.scene = scene
        self.camera = copy(camera)
        self._width, self._height = map(float, logical_size)
        if self._width <= 0 or self._height <= 0:
            raise ValueError("Annotation canvas dimensions must be positive")
        self.camera.aspect = self._width / self._height
        self._occluded = occluded
        self._hover_entity = hover

    def width(self):
        return self._width

    def height(self):
        return self._height

    def _occluded_on_screen(self, point):
        return bool(self._occluded(point)) if self._occluded else False

    def _project_samples(self, points):
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        return [(self._world_to_pixel(p, mvp), not self._occluded_on_screen(p))
                for p in points]


def guide_segments(scene, camera):
    """Return GL world dash vertices (N,2,3) and selected flags (N,).

    P1/P2 may upload these to a depth-tested line pass instead of painting them.
    Includes finite guide-point origin segments and layer visibility filtering.
    """
    distance = max(float(camera.distance), 1e-3)
    coords, spans = _guide_vertices(
        shown_guides(scene), distance * .03, scene.selection,
        centre=camera.target, reach=distance * 15,
        eye=camera.eye() if camera.perspective else None)
    segments = np.asarray(coords, dtype=np.float32).reshape(-1, 2, 3)
    selected = np.zeros(len(segments), dtype=bool)
    for start, count, flag in spans:
        selected[start // 2:(start + count) // 2] = flag
    return segments, selected


def draw_guide_lines(painter, layout):
    """Project GL world dashes; no depth-buffer occlusion is possible here."""
    segments, selected = guide_segments(layout.scene, layout.camera)
    pens = [QPen(QColor.fromRgbF(*rgb), 1.0) for rgb in
            ((.27, .35, .47), (.95, .45, .16))]
    for pen in pens:
        pen.setCapStyle(Qt.FlatCap)
    painter.save()
    try:
        for (a, b), flag in zip(segments, selected):
            clipped = layout._clip_segment_front(QVector3D(*a), QVector3D(*b))
            if clipped is None:
                continue
            pa, pb = (layout._world_to_pixel(p) for p in clipped)
            if pa is None or pb is None:
                continue
            visible = layout._clip_pixel_line(pa, pb)
            if visible is not None:
                painter.setPen(pens[int(flag)])
                painter.drawLine(QPointF(*visible[0]), QPointF(*visible[1]))
    finally:
        painter.restore()


def draw_annotations(painter, scene, camera, logical_size, *, annotations_only=False,
                     occluded=None, hover=None):
    """Paint document annotations; return the isolated AnnotationLayout for snaps."""
    layout = AnnotationLayout(scene, camera, logical_size, occluded=occluded, hover=hover)
    painter.save()
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        if not annotations_only:
            draw_guide_lines(painter, layout)
            layout._draw_guides(painter)
            layout._draw_section_planes(painter)
            layout._draw_geo_surfaces(painter)
            layout._draw_geo_paths(painter)
            layout._draw_geo_points(painter)
        layout._draw_dimensions(painter)
        layout._draw_text_labels(painter)
    finally:
        painter.restore()
    return layout


def composite_annotations(image, scene, camera, *, logical_size,
                          overlays=True, annotations_only=False, occluded=None):
    """Return a capture copy with annotations placed for its scale and aspect.

    image dimensions are physical pixels; logical_size is the live logical size.
    DPR metadata is respected exactly once, including a 2x QImage.
    """
    result = image.copy()
    if not overlays:
        return result
    if result.isNull():
        raise ValueError("Cannot annotate a null image")
    width, height = map(float, logical_size)
    if width <= 0 or height <= 0:
        raise ValueError("Annotation canvas dimensions must be positive")
    scale = result.width() / width
    canvas = (width, result.height() / scale)
    painter = QPainter(result)
    try:
        factor = scale / result.devicePixelRatio()
        painter.scale(factor, factor)
        draw_annotations(painter, scene, camera, canvas,
                         annotations_only=annotations_only, occluded=occluded)
    finally:
        painter.end()
    return result


def draw_tool_overlays(painter, tools, *, labels=True):
    """Call active tool's GL painter hook, then prioritized lock/reference labels.

    P1 passes NativeTools (or a GL-compatible facade), every live frame regardless
    of document annotations. No export call. Returns without altering painter state.
    """
    tool = getattr(tools, "tool", getattr(tools, "active_tool", None))
    painter.save()
    try:
        painter.setBrush(Qt.NoBrush)
        hook = getattr(tool, "draw_overlay", None)
        if callable(hook):
            hook(tools, painter)
        if not labels:
            return
        if getattr(tools, "reference_mode", None) is not None:
            Viewport._draw_reference_label(tools, painter)
        elif getattr(tools, "axis_lock", None) is not None:
            Viewport._draw_axis_lock_label(tools, painter)
        elif getattr(tool, "plane_lock", None) is not None:
            # NativeTools may still expose source.active_tool; use the actual tool.
            from types import SimpleNamespace
            Viewport._draw_plane_lock_label(SimpleNamespace(active_tool=tool), painter)
        else:
            Viewport._draw_inference_label(tools, painter)
        if getattr(tools, "linear_inference_mode", "all") != "all":
            Viewport._draw_linear_mode_label(tools, painter)
    finally:
        painter.restore()
