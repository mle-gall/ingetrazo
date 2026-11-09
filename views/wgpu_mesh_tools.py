"""Document-tool facade for native mesh editing; no GL picking or drawing."""
import numpy as np
from PySide6.QtGui import QColor, QVector3D, QMatrix4x4
from views.wgpu_overlay import Primitive
from core.group import iter_placements


class MeshToolAccess:
    mesh_outline_preview = True
    # Do not borrow the GL viewport's cached loose-edge screen projection.
    _ledge_screen = None
    _OCCLUSION_STEP_PX = 12.
    _OCCLUSION_MAX_SAMPLES = 128
    _OCCLUSION_SPLIT = 8
    _OCCLUSION_ROUNDS = 2

    @staticmethod
    def _text_block_x(*args):
        from views.viewport import Viewport
        return Viewport._text_block_x(*args)

    @staticmethod
    def _format_dim_value(*args):
        from views.viewport import Viewport
        return Viewport._format_dim_value(*args)


    def inference_meshes(self, x, y):
        picked = self._picked_mesh(x, y)
        # Other placements are queried through their world-space face plane;
        # their local vertices must not be projected as world coordinates.
        return [self.scene.mesh]

    def work_point(self, x, y):
        from core import axes
        tool = self.tool
        plane = tool.drag_plane(self) or getattr(tool, 'work_plane', None)
        if plane is None:
            lock = getattr(tool, 'locked_work_plane', None)
            anchor = self.start_point if self.start_point is not None else axes.origin()
            plane = lock(anchor) if lock else None
        if plane is None:
            face, placement = self.pick_face_placement(x, y)
            if face is not None:
                from core.snap import face_plane_world
                plane = face_plane_world(face, getattr(placement, 'xform', None))
        if plane is None:
            anchor = self.start_point if self.start_point is not None else axes.origin()
            normal = axes.axis('z')
            if abs(QVector3D.dotProduct(self.camera.forward(), normal)) < .2:
                normal = self.camera.forward()
            plane = anchor, normal
        self._last_work_plane = plane
        return self._ray_hit_plane((x, y), plane)

    def _segment_to_pixels(self, a, b):
        pa, pb = self._world_to_pixel(a), self._world_to_pixel(b)
        return (pa, pb) if pa is not None and pb is not None else None

    def _pixel_to_ray(self, x, y):
        return self.view._pixel_to_ray(x, y)

    def _world_to_pixel(self, point, mvp=None):
        return self.view._world_to_pixel(point)

    def _project_to_lock_line(self, *args):
        return self.view._project_to_lock_line(*args)

    def _ray_hit_plane(self, cursor, plane):
        from views.viewport import Viewport
        return Viewport._ray_hit_plane(self, cursor, plane)

    def _picked_mesh(self, x, y):
        row = self.view.pick_row(x, y)
        resolved = self.view.resolve(row)
        if resolved is None:
            return None
        group, code = resolved
        matrix = QMatrix4x4(self.view.packed.instances['world'][row].T.flatten().tolist())
        mesh = group.mesh if group is not None else self.scene.loose_mesh
        return mesh, group, matrix

    def pick_face_placement(self, x, y):
        from views.viewport import _ray_triangle
        from types import SimpleNamespace
        picked = self._picked_mesh(x, y)
        if picked is None:
            return None, None
        mesh, group, matrix = picked
        origin, direction = self._pixel_to_ray(x, y)
        inverse, ok = matrix.inverted()
        if not ok:
            return None, None
        origin = inverse.map(origin)
        direction = inverse.mapVector(direction)
        best, distance = None, float('inf')
        excluded = getattr(self.tool, 'moving_face_ids', lambda: set())()
        for face in mesh.faces:
            if id(face) in excluded:
                continue
            if getattr(face, 'hidden', False):
                continue
            for triangle in face.triangulate():
                t = _ray_triangle(origin, direction, *triangle)
                if t is not None and t < distance:
                    best, distance = face, t
        return best, (SimpleNamespace(xform=matrix) if group is not None else None)

    def pick_face_any(self, x, y):
        face, _ = self.pick_face_placement(x, y)
        picked = self._picked_mesh(x, y)
        if picked is None:
            return None, None
        mesh, group, _ = picked
        if mesh is self.scene.mesh:
            return face, None
        return (face, group) if group is not None else (None, None)

    def pick_face(self, x, y):
        face, group = self.pick_face_any(x, y)
        return face if group is None and self.scene.entity_selectable(face) else None

    def pick_group(self, x, y):
        picked = self._picked_mesh(x, y)
        if picked is None or picked[0] is self.scene.mesh:
            return None
        group = picked[1]
        target = self.view.context_placement(group)
        return target if target is not None and self.scene.entity_selectable(target) else None

    def pick_locked_group(self, x, y):
        picked = self._picked_mesh(x, y)
        target = self.view.context_placement(picked[1]) if picked else None
        if target is not None and getattr(target, 'locked', False):
            visible, layer_locked = self.scene._layer_state(target)
            if visible and not layer_locked:
                return target
        return None

    def pick_locked_image_plane(self, x, y):
        from views.viewport import Viewport
        return Viewport.pick_locked_image_plane(self, x, y)

    def _face_or_image_in_front(self, x, y):
        return self.pick_face(x, y)

    def _context_pick(self, x, y):
        from views.viewport import Viewport
        return Viewport._context_pick(self, x, y)

    def pick_edge(self, x, y):
        best, distance = None, 12.
        for edge in self.scene.mesh.edges:
            if not self.scene.entity_selectable(edge) or (
                    (getattr(edge, 'hidden', False) or getattr(edge, 'soft', False))
                    and not self.scene.show_hidden_geometry):
                continue
            a, b = self._world_to_pixel(edge.a), self._world_to_pixel(edge.b)
            if a is None or b is None:
                continue
            a, b = np.asarray(a), np.asarray(b)
            d = b-a
            t = np.clip(np.dot(np.array([x, y])-a, d)/max(np.dot(d, d), 1e-12), 0, 1)
            dist = np.linalg.norm(a+t*d-[x, y])
            if dist < distance and not self._is_occluded(edge.a + (edge.b-edge.a)*float(t)):
                best, distance = edge, dist
        return best

    pick_visible_edge = pick_edge

    def _project_px(self, pts):
        matrix = np.asarray((self.view.camera.projection_matrix() *
                             self.view.camera.view_matrix()).data()).reshape(4, 4).T
        clip = pts @ matrix[:, :3].T + matrix[:, 3]
        ok = clip[:, 3] > 0
        w = np.where(ok, clip[:, 3], 1.)
        return ((clip[:, 0]/w*.5+.5)*self.view.width(),
                (1.-(clip[:, 1]/w*.5+.5))*self.view.height(), ok)

    def _is_occluded(self, point):
        from views.wgpu_inference import surface
        pixel = self._world_to_pixel(point)
        if pixel is None:
            return True
        row = self.view.pick_row(*pixel)
        if row is None or self.view.inference_index is None:
            return False
        origin, direction = self._pixel_to_ray(*pixel)
        hit = surface(self.view.inference_index, row, origin, direction)
        return hit is not None and (hit-origin).length() + 1e-4 < (point-origin).length()

    def set_hover(self, entity, placement=None):
        self._mesh_hover = self._hover_entity = entity

    def set_suppressed_faces(self, faces):
        if type(getattr(self, 'tool', None)).__name__ == 'TexturePositionTool':
            # TexturePreview replaces the resident material stream itself;
            # suppressing the base would also suppress its mapped preview.
            return
        faces = tuple(faces or ())
        if {id(f) for f in faces} == {id(f) for f in getattr(self.view, 'suppressed_faces', ())}:
            return
        self.view.suppressed_faces = faces
        # The existing packer accepts per-face paint overrides. Hide only the
        # preview's base faces without mutating the document or its history.
        self.view.set_scene(self.scene)
        self.view.update()

    def mesh_feedback(self):
        lines = list(self.tool.rubber_band_lines())
        lines.extend(self.tool.guide_preview_lines())
        faces = list(getattr(self.tool, 'preview_faces', lambda: [])())
        self.view.preview_faces = faces
        # TODO(P2): set_preview_faces accepts world-space triangle float3s;
        # an empty (0,3,3) array clears the depth-tested transient pass.
        transient = getattr(getattr(self.view, 'renderer', None), 'set_preview_faces', None)
        if transient is not None:
            triangles = [tuple(p.toTuple() for p in tri)
                         for face in faces for tri in face.triangulate()]
            transient(np.asarray(triangles, np.float32).reshape(-1, 3, 3))
        # Until P2 lands, show the outline, never an unoccluded face fill.
        for face in faces:
            points = list(getattr(face, 'vertices', face))
            lines.extend(zip(points, points[1:] + points[:1]))

        state = getattr(self.tool, 'scale_box_state', lambda: None)()
        if state:
            lines.extend(state['segments'])
            for point, role in state['grips']:
                pixel = self._world_to_pixel(point)
                if pixel is not None:
                    x, y = pixel
                    color = '#55dd55' if role == 'idle' else '#ff5555'
                    self.view.overlay_primitives.append(Primitive(
                        'rectangle', ((x-4, y-4), (x+4, y+4)), color, fill=color))

        entity = getattr(self, '_mesh_hover', None)
        if entity is not None:
            if hasattr(entity, 'vertices'):
                points = entity.vertices
                lines.extend(zip(points, points[1:] + points[:1]))
            elif hasattr(entity, 'a'):
                lines.append((entity.a, entity.b))
        rgba = getattr(self.tool, 'wireframe_color', None)
        color = QColor.fromRgbF(*rgba).name() if rgba else '#00dfff'
        if type(self.tool).__name__ == 'EraserTool':
            color = '#ff5555'
        for a, b in lines:
            pa, pb = self._world_to_pixel(a), self._world_to_pixel(b)
            if pa is not None and pb is not None:
                self.view.overlay_primitives.append(Primitive(
                    'polyline', (pa, pb), color))
        label = self.tool.value_label() if hasattr(self.tool, 'value_label') else None
        if label is not None:
            text, point = label
            pixel = self._world_to_pixel(point) if point is not None else (16, 24)
            if pixel is not None:
                self.view.overlay_primitives.append(Primitive('text', (pixel,), text=text))
            self.measurementChanged.emit(text)

    def draw_annotations(self, painter):
        from views.viewport import Viewport
        self._hover_entity = getattr(self, '_mesh_hover', None)
        marks = getattr(self.view, '_draw_selection_marks', None)
        if marks is not None:
            marks(painter)
        Viewport._draw_dimensions(self, painter)
        Viewport._draw_text_labels(self, painter)
        Viewport._draw_geo_paths(self, painter)
        Viewport._draw_guides(self, painter)
        from views.viewport import shown_guides
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtGui import QPen
        painter.setPen(QPen(QColor('#465a78'), 1, Qt.DashLine))
        for guide in shown_guides(self.scene):
            if guide.is_line:
                segment = Viewport._guide_snap_segment(self, guide)
                if segment is not None:
                    pixels = self._segment_to_pixels(*segment)
                    if pixels is not None:
                        painter.drawLine(QPointF(*pixels[0]), QPointF(*pixels[1]))
        if getattr(self, 'reference_mode', None) is not None:
            Viewport._draw_reference_label(self, painter)
        elif getattr(self, 'axis_lock', None) is not None:
            Viewport._draw_axis_lock_label(self, painter)
        elif getattr(self.tool, 'plane_lock', None) is not None:
            Viewport._draw_plane_lock_label(self, painter)
        elif self.last_snap is not None:
            Viewport._draw_inference_label(self, painter)
        if getattr(self, 'linear_inference_mode', 'all') != 'all':
            Viewport._draw_linear_mode_label(self, painter)
        hook = getattr(self.tool, 'draw_overlay', None)
        if hook is not None:
            hook(self, painter)

    def _draw_occluded_segment(self, painter, a, b):
        from views.viewport import Viewport
        Viewport._draw_occluded_segment(self, painter, a, b)

    def _project_samples(self, points):
        return [(self._world_to_pixel(p), not self._is_occluded(p)) for p in points]

    def _occluded_on_screen(self, point):
        return self._is_occluded(point)

    def pick_dimension(self, *args, **kwargs):
        from views.viewport import Viewport
        return Viewport.pick_dimension(self, *args, **kwargs)

    def pick_text_label(self, *args, **kwargs):
        from views.viewport import Viewport
        return Viewport.pick_text_label(self, *args, **kwargs)

    def _unsupported_pick(self, *args, **kwargs):
        return None

    def pick_geopath(self, *args):
        from views.viewport import Viewport
        return Viewport.pick_geopath(self, *args)

    def _draw_geo_path_label(self, *args):
        from views.viewport import Viewport
        return Viewport._draw_geo_path_label(self, *args)

    def section_plane_frame(self, plane):
        from views.viewport import Viewport
        return Viewport.section_plane_frame(self, plane)

    def _clip_segment_front(self, a, b):
        from views.viewport import Viewport
        return Viewport._clip_segment_front(self, a, b)

    def pick_section_plane(self, x, y):
        from views.viewport import Viewport
        return Viewport.pick_section_plane(self, x, y)

    pick_image = _unsupported_pick
    pick_image_plane = _unsupported_pick
    _group_obb = _unsupported_pick
    def begin_groups_preview(self, groups):
        selected = {g.uid for root in groups for g, _ in iter_placements(root)}
        self.ids = np.asarray([row for uid in selected
                               for row in self.view.uid_rows.get(uid, ())], np.int64)
        billboards = getattr(self.view, '_billboards', None)
        if billboards is not None:
            billboards.restore()
            billboards.key = None
        self.original = self.view.packed.instances[self.ids].copy()

    def set_groups_preview_offset(self, delta):
        matrix = QMatrix4x4()
        matrix.translate(delta)
        self.set_groups_preview_matrix(matrix)

    def set_groups_preview_matrix(self, matrix):
        if self.original is None:
            return
        transform = np.asarray(matrix.data(), np.float32).reshape(4, 4).T
        rows = self.original.copy()
        rows['world'] = (transform @ rows['world'].transpose(0, 2, 1)).transpose(0, 2, 1)
        self.write_rows(rows)

    def end_groups_preview(self):
        self.restore()
        self.original = None

    image_plane_at = _unsupported_pick

    def _nearby_loose_edges(self, *args, **kwargs):
        return []

    _nearby_group_edges = _nearby_loose_edges
