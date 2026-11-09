"""Edit-context membership and screen scaffolding shared by native captures."""
import math
import numpy as np
from PySide6.QtGui import QVector3D


def rest_rows(groups, context):
    if context is None:
        return []
    from core.group import iter_placements
    subject = {id(g) for g, _ in iter_placements(context)}
    return [row for row, group in enumerate(groups) if id(group) not in subject]


def box_primitives(view):
    from views.viewport import Viewport, _box_edge_vertices
    from views.wgpu_overlay import Primitive
    source = view.source_viewport
    if source is None or source.plano_style is not None or source.style_override is not None:
        return []
    box = view._edit_group_box_corners()
    if box is None:
        return []
    scale = view.devicePixelRatioF()
    dash = min(20., max(3., .003 * view.height() * scale /
                       math.tan(math.radians(view.camera.fov_deg) / 2))) / scale
    result = []
    for a, b in np.asarray(_box_edge_vertices(box)).reshape(-1, 2, 3):
        segment = Viewport._clip_segment_front(view, QVector3D(*a), QVector3D(*b))
        if segment is None:
            continue
        points = tuple(view._world_to_pixel(p) for p in segment)
        if all(p is not None for p in points):
            result.append(Primitive('polyline', points, '#5a6e8c', 1 / scale,
                                    dash=(dash * scale, dash * scale)))
    return result
