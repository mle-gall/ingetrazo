"""Document-tool facade for native mesh editing; no GL picking or drawing."""
import numpy as np
from PySide6.QtGui import QVector3D, QMatrix4x4
from views.wgpu_overlay import Primitive
from core.group import iter_placements


class MeshToolAccess:
    mesh_outline_preview = True

    def inference_meshes(self, x, y):
        picked = self._picked_mesh(x, y)
        return [self.scene.mesh] if picked is None else [self.scene.mesh, picked[0]]

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

    def _pixel_to_ray(self, x, y):
        return self.view._pixel_to_ray(x, y)

    def _world_to_pixel(self, point):
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
        for face in mesh.faces:
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
        return face, group

    def pick_face(self, x, y):
        face, group = self.pick_face_any(x, y)
        return face if group is None and self.scene.entity_selectable(face) else None

    def pick_group(self, x, y):
        picked = self._picked_mesh(x, y)
        if picked is None or picked[0] is self.scene.mesh:
            return None
        group = picked[1]
        # Resolve nested placements to the selectable context owner.
        while group is not None and not self.scene.entity_selectable(group):
            group = next((g for root in self.scene.groups
                          for g, _ in iter_placements(root)
                          if group in (g.children or ())), None)
        return group

    def pick_edge(self, x, y):
        picked = self._picked_mesh(x, y)
        if picked is None or picked[0] is not self.scene.mesh:
            return None
        best, distance = None, 12.
        for edge in picked[0].edges:
            if getattr(edge, 'hidden', False) or getattr(edge, 'soft', False):
                continue
            a, b = self._world_to_pixel(edge.a), self._world_to_pixel(edge.b)
            if a is None or b is None:
                continue
            a, b = np.asarray(a), np.asarray(b)
            d = b-a
            t = np.clip(np.dot(np.array([x, y])-a, d)/max(np.dot(d, d), 1e-12), 0, 1)
            dist = np.linalg.norm(a+t*d-[x, y])
            if dist < distance:
                best, distance = edge, dist
        return best

    pick_visible_edge = pick_edge

    def set_hover(self, entity):
        self._mesh_hover = entity

    def set_suppressed_faces(self, faces):
        # The native sweep is an outline; the resident base remains visible.
        pass

    def mesh_feedback(self):
        lines = list(self.tool.rubber_band_lines())
        entity = getattr(self, '_mesh_hover', None)
        if entity is not None:
            if hasattr(entity, 'vertices'):
                points = entity.vertices
                lines.extend(zip(points, points[1:] + points[:1]))
            elif hasattr(entity, 'a'):
                lines.append((entity.a, entity.b))
        for a, b in lines:
            pa, pb = self._world_to_pixel(a), self._world_to_pixel(b)
            if pa is not None and pb is not None:
                self.view.overlay_primitives.append(Primitive(
                    'polyline', (pa, pb), '#ff5555' if type(self.tool).__name__ == 'EraserTool' else '#00dfff'))
        label = self.tool.value_label() if hasattr(self.tool, 'value_label') else None
        if label is not None:
            text, point = label
            pixel = self._world_to_pixel(point)
            if pixel is not None:
                self.view.overlay_primitives.append(Primitive('text', (pixel,), text=text))
            self.measurementChanged.emit(text)

    # These annotations are outside R3a. Never fall through to the GL index.
    def pick_dimension(self, *args, **kwargs):
        return None

    pick_geopath = pick_dimension
    pick_text_label = pick_dimension
    pick_section_plane = pick_dimension
    pick_image = pick_dimension
    pick_image_plane = pick_dimension
    _group_obb = pick_dimension
    end_groups_preview = pick_dimension
    image_plane_at = pick_dimension

    def _nearby_loose_edges(self, *args, **kwargs):
        return []

    _nearby_group_edges = _nearby_loose_edges
