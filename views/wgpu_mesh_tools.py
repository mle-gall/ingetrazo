"""Document-tool facade for native mesh editing; no GL picking or drawing."""
import numpy as np
from PySide6.QtGui import QColor, QVector3D, QMatrix4x4
from views.wgpu_overlay import Primitive
from core.group import iter_placements


class MeshToolAccess:
    mesh_outline_preview = True
    # Do not borrow the GL viewport's cached loose-edge screen projection.
    _ledge_screen = None
    _group_chunk = None  # SelectTool uses its model-space box traversal.
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
        if mvp is None:
            return self.view._world_to_pixel(point)
        from views.viewport import Viewport
        return Viewport._world_to_pixel(self, point, mvp)

    def _project_to_lock_line(self, *args):
        return self.view._project_to_lock_line(*args)

    def _ray_hit_plane(self, cursor, plane):
        from views.viewport import Viewport
        return Viewport._ray_hit_plane(self, cursor, plane)

    def _picked_mesh(self, x, y):
        row = self._selection_row(x, y) if self.mode == 'select' else self.view.pick_row(x, y)
        resolved = self.view.resolve(row)
        if resolved is None:
            return None
        group, _ = resolved
        matrix = QMatrix4x4(self.view.packed.instances['world'][row].T.flatten().tolist())
        mesh = group.mesh if group is not None else self.scene.loose_mesh
        if group is self.scene.edit_group and group is not None:
            # The editing mesh is in world coordinates even if the retained
            # GPU row still draws its local-space definition.
            matrix = QMatrix4x4()
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
        if group is self.scene.edit_group:
            return face, None
        return (face, group) if group is not None else (None, None)

    def pick_face(self, x, y):
        face, group = self.pick_face_any(x, y)
        return face if group is None and self.scene.entity_selectable(face) else None

    def _selection_row(self, x, y):
        row = self.view.pick_row(x, y)
        context = self.scene.edit_group
        if context is not None:
            group = self.view.packed.groups[row] if row is not None else None
            if group is not context and self.view.context_placement(group) is None:
                # Fade retains depth. GL picks only the editable subtree,
                # even when another placement covers it in the ID pass.
                from views.wgpu_inference import context_hit
                row = (context_hit(self.view, context, x, y)
                       if self.view.inference_index is not None else None)
        return row

    def pick_group(self, x, y):
        row = self._selection_row(x, y)
        self.view.hovered_row = row
        group = self.view.packed.groups[row] if row is not None else None
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
        renderer = getattr(self.view, 'renderer', None)
        if renderer is not None and hasattr(renderer, 'set_suppressed_faces'):
            from views.wgpu_parity import face_ranges
            renderer.set_suppressed_faces(face_ranges(self.view, faces))
        self.view.update()

    def mesh_feedback(self):
        lines = list(self.tool.rubber_band_lines())
        lines.extend(self.tool.guide_preview_lines())
        faces = list(getattr(self.tool, 'preview_faces', lambda: [])())
        self.view.preview_faces = faces
        renderer = getattr(self.view, 'renderer', None)
        if renderer is not None and hasattr(renderer, 'set_preview_mesh'):
            from views.wgpu_parity import preview_mesh
            edges = [(a, b) for face in faces
                     for a, b in zip(face.vertices, face.vertices[1:] + face.vertices[:1])]
            renderer.set_preview_mesh(*preview_mesh(faces, edges))

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
        from views.wgpu_annotations import draw_annotations, draw_tool_overlays
        from views.wgpu_overlay import draw_snap_indicator
        self._hover_entity = getattr(self, '_mesh_hover', None)
        marks = getattr(self.view, '_draw_selection_marks', None)
        if marks is not None:
            marks(painter)
        layout = draw_annotations(painter, self.scene, self.camera,
            (painter.device().width()/painter.device().devicePixelRatioF(),
             painter.device().height()/painter.device().devicePixelRatioF()), occluded=self._is_occluded,
            hover=self._hover_entity)
        draw_tool_overlays(painter, self)
        snap = self.last_snap
        if snap is not None and getattr(snap, 'kind', None) and hasattr(snap, 'color'):
            draw_snap_indicator(painter, snap, layout._world_to_pixel,
                                layout._clip_pixel_line, labels=False)

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
    def pick_image_plane(self, x, y):
        from views.viewport import Viewport
        return Viewport.image_plane_at(self, x, y, selectable_only=True)

    def image_in_front_of(self, face, x, y):
        from views.viewport import Viewport
        return Viewport.image_in_front_of(self, face, x, y)

    def edge_point_under_cursor(self, edge, x, y):
        from views.viewport import Viewport
        return Viewport.edge_point_under_cursor(self, edge, x, y)

    def pick_extension_item(self, x, y):
        from views.viewport import Viewport
        return Viewport.pick_extension_item(self, x, y)

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

    def _resident_nearby_edges(self, px, py, radius_px=48., cap=48):
        from views.wgpu_inference import nearby_edges
        v = self.view
        if v.inference_index is None:
            return []
        return nearby_edges(v.inference_index, v.packed, v.camera, v.width(),
                            v.height(), px, py, radius_px=radius_px, cap=cap,
                            edit_group=self.scene.edit_group)

    def _nearby_loose_edges(self, px, py, radius_px=64., cap=400):
        return [e for e in self._resident_nearby_edges(px, py, radius_px, cap) if not e.in_group]

    def _nearby_group_edges(self, px, py, radius_px=48., cap=48):
        return [e for e in self._resident_nearby_edges(px, py, radius_px, cap) if e.in_group]

    def reference_tangent(self, point):
        """Arc continuation from bounded resident curve features, not GL scans."""
        from views.wgpu_inference import tangent_direction
        v = self.view
        if getattr(v, 'inference_index', None) is None:
            return None
        pixel = v._world_to_pixel(point)
        if pixel is None:
            return None
        edges = self._resident_nearby_edges(*pixel, radius_px=12., cap=48)
        for row in dict.fromkeys(edge.row for edge in edges):
            direction = tangent_direction(v.inference_index, v.packed, row, point)
            if direction is not None:
                return direction
        return None
