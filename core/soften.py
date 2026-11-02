# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoable angle-based smoothing without changing topology or hidden flags."""
import math
from core.group import Group
from core.mesh import Edge, Face
from core.history import Command


def selected_edges(scene):
    """One entry per prototype mesh; face selections affect internal seams."""
    targets = {}
    faces = {e for e in scene.selection if isinstance(e, Face)}
    edges = {e for e in scene.selection if isinstance(e, Edge)}
    for face in faces:
        for edge in {e for loop in (face.loop, *face.hole_loops)
                     for vertex in loop for e in vertex.edges}:
            if len(edge.faces) == 2 and all(f in faces for f in edge.faces):
                edges.add(edge)
    if edges:
        targets[scene.mesh] = edges
    pending = [g for g in scene.selection if isinstance(g, Group)]
    visited = set()
    while pending:
        group = pending.pop()
        if id(group) in visited or getattr(group, 'locked', False):
            continue
        visited.add(id(group))
        pending.extend(group.children or ())
        if group.mesh not in targets:
            targets[group.mesh] = set(group.mesh.edges)
        else:
            targets[group.mesh].update(group.mesh.edges)
    return targets


class SoftenByAngleCommand(Command):
    keeps_bounds = True

    def __init__(self, targets, angle=30.0, coplanar=True, harden=False):
        self.targets = targets
        self.angle = float(angle)
        if not math.isfinite(self.angle) or not 0 <= self.angle <= 180:
            raise ValueError('Angle must be between 0 and 180 degrees')
        self.coplanar = coplanar
        self.harden = harden
        self.changes = None

    def _prepare(self):
        changes = []
        normals = {}
        for mesh, edges in self.targets.items():
            for edge in edges:
                soft = False
                if not self.harden and len(edge.faces) == 2:
                    a, b = edge.faces
                    if a not in normals:
                        normals[a] = a.normal().normalized()
                    if b not in normals:
                        normals[b] = b.normal().normalized()
                    na, nb = normals[a], normals[b]
                    if not na.isNull() and not nb.isNull():
                        dot = max(-1., min(1., na.dotProduct(na, nb)))
                        angle = math.degrees(math.acos(dot))
                        soft = angle <= self.angle + 1e-5 and (self.coplanar or angle > 1e-4)
                if bool(edge.soft) != soft:
                    changes.append((mesh, edge, bool(edge.soft), soft))
        return changes

    def _apply(self, scene, after):
        meshes = set()
        for mesh, edge, old, new in self.changes:
            edge.soft = new if after else old
            meshes.add(mesh)
        for mesh in meshes:
            mesh._chunk_dirty = True
            mesh._attrs_dirty = True
            mesh._render_attrs_serial = getattr(mesh, '_render_attrs_serial', 0) + 1
        if meshes:
            scene.version += 1

    def do(self, scene):
        if self.changes is None:
            self.changes = self._prepare()
        self._apply(scene, True)

    def undo(self, scene):
        self._apply(scene, False)
