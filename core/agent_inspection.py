# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured main-thread inspection and navigation for the agent bridge."""
from collections import Counter
from fnmatch import fnmatchcase
import math

from PySide6.QtGui import QMatrix4x4, QVector3D
from core.group import placement_points


def vector(v):
    return [v.x(), v.y(), v.z()]


def bounds(pair):
    lo, hi = pair
    return None if lo is None else {"min": vector(lo), "max": vector(hi)}


class InspectionTools:
    def _groups(self):
        # Every tool starts from this walk; a sweep of one query_entity per
        # group on a 20k-placement model repeated it 20k times. Any edit
        # moves scene.version, so that is the cache key (selection and
        # camera changes leave the tree alone).
        scene = self._viewport.scene
        key = (id(scene), scene.version, len(scene.groups))
        cached = getattr(self, "_groups_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]

        def walk(groups, parents, base):
            for g in groups:
                matrix = g.xform
                if base is not None:
                    matrix = base if matrix is None else base * matrix
                yield g, parents, matrix
                yield from walk(g.children or [], parents + [g], matrix)
        rows = list(walk(scene.groups, [], None))
        self._groups_cache = (key, rows)
        return rows

    def _find(self, uid):
        for row in self._groups():
            if row[0].uid == uid:
                return row
        raise ValueError(f"unknown group uid {uid!r}")

    def _row(self, group, parents, matrix):
        layer = next((l for l in self._viewport.scene.layers if l.name == group.layer), None)
        # Stable for the lifetime of this document, including undo; no raw addresses.
        keys = getattr(self, "_definition_keys", None)
        if keys is None:
            keys = self._definition_keys = {}
        import weakref
        if not isinstance(keys, weakref.WeakKeyDictionary):
            keys = self._definition_keys = weakref.WeakKeyDictionary()
        if group.mesh not in keys:
            from uuid import uuid4
            keys[group.mesh] = uuid4().hex
        # Content that comes from a linked file is read-only for the host:
        # the agent must see it to leave it alone (and the exporter skips it).
        from core.links import link_of
        source = next((link_of(g)["path"] for g in [*parents, group] if link_of(g)), None)
        return dict(uid=group.uid, name=group.name,
                    linked=source is not None, link_source=source,
                    parent_uid=parents[-1].uid if parents else None, depth=len(parents),
                    children_count=len(group.children or []),
                    is_component_instance=group.xform is not None,
                    shared_definition_key=keys[group.mesh], hidden=group.hidden,
                    layer={"name": group.layer, "uid": layer.uid if layer else None},
                    ifc=group.ifc)

    def _group_bounds(self, group, parents, matrix):
        # placement_points already composes descendants. Supply ancestors via
        # a temporary placement wrapper without modifying the live tree.
        from types import SimpleNamespace
        wrapper = SimpleNamespace(mesh=group.mesh, xform=matrix,
                                  children=group.children or [])
        pts = placement_points(wrapper)
        if not len(pts):
            return None
        return {"min": pts.min(axis=0).tolist(), "max": pts.max(axis=0).tolist()}

    def _tool_query_selection(self):
        scene = self._viewport.scene
        counts = dict(Counter(type(e).__name__ for e in scene.selection))
        groups = [r for r in self._groups() if r[0] in scene.selection]
        from types import SimpleNamespace
        from core.scene import Scene
        loose = scene.selection - {r[0] for r in groups}
        box = bounds(Scene.selection_bounds(SimpleNamespace(selection=loose)))
        boxes = [self._group_bounds(*r) for r in groups]
        # The scene helper handles loose entities; nested groups require ancestors.
        if groups and len(groups) == len(scene.selection):
            box = None
        for b in boxes:
            if b:
                box = b if box is None else {"min": [min(a, c) for a, c in zip(box["min"], b["min"])],
                                             "max": [max(a, c) for a, c in zip(box["max"], b["max"])]}
        return dict(counts=counts, groups=[dict(uid=g.uid, name=g.name,
                    **{"class": (g.ifc or {}).get("class")}) for g, _, _ in groups],
                    faces=counts.get("Face", 0), edges=counts.get("Edge", 0), bounds=box)

    def _tool_select(self, uids=None, names=None, mode="replace", pattern=None):
        if mode not in ("replace", "add", "remove", "clear"):
            raise ValueError("mode must be replace, add, remove or clear")
        selected = {self._find(uid)[0] for uid in (uids or [])}
        patterns = ([names] if isinstance(names, str) else (names or [])) + ([pattern] if pattern else [])
        selected.update(g for g, _, _ in self._groups()
                        if any(fnmatchcase(g.name or "", p) for p in patterns))
        scene = self._viewport.scene
        if mode == "clear":
            scene.clear_selection()
        elif mode == "remove":
            scene.select(selected, mode="remove")
        else:
            scene.select(selected, additive=mode == "add")
        self._viewport.update()
        return self._tool_query_selection()

    def _tool_query_tree(self, root_uid=None, depth=2, offset=0, limit=200, include_hidden=True):
        if type(depth) is not int or depth < 0 or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("depth/offset must be nonnegative and limit between 1 and 1000")
        root = self._find(root_uid)[0] if root_uid else None
        root_depth = len(self._find(root_uid)[1]) if root else 0
        # Select first, build rows only for the page: a 91k-group model is
        # paged in ~100 calls, and each used to build every row to slice it.
        selected = []
        for g, parents, matrix in self._groups():
            if root is not None and g is not root and root not in parents:
                continue
            relative = len(parents) - root_depth
            if relative > depth or (not include_hidden and any(p.hidden for p in [*parents, g])):
                continue
            selected.append((g, parents, matrix, relative))
        rows = []
        for g, parents, matrix, relative in selected[offset:offset + limit]:
            row = self._row(g, parents, matrix)
            row["depth"] = relative
            rows.append(row)
        total = len(selected)
        return dict(rows=rows, total=total,
                    next_offset=offset + limit if offset + limit < total else None,
                    version=self._viewport.scene.version)

    def _tool_query_entity(self, uid):
        g, parents, matrix = self._find(uid)
        row = self._row(g, parents, matrix)
        row.update(bounds=self._group_bounds(g, parents, matrix),
                   local_matrix=list((g.xform or QMatrix4x4()).data()),
                   placement_matrix=list((matrix or QMatrix4x4()).data()),
                   faces=len(g.mesh.faces), edges=len(g.mesh.edges),
                   materials=sorted({f.attrs["mat"] for f in g.mesh.faces if f.attrs.get("mat")}),
                   children=[c.uid for c in g.children or []], path=[p.name for p in parents])
        return row

    def _tool_query_layers(self):
        scene = self._viewport.scene
        groups = [g for g, _, _ in self._groups()]
        meshes = {id(g.mesh): g.mesh for g in groups}
        meshes[id(scene.loose_mesh)] = scene.loose_mesh
        from core.layers import DEFAULT_LAYER
        rows = []
        for layer in scene.layers:
            path, folder = [], layer.folder
            while folder and folder not in path:
                path.insert(0, folder)
                folder = getattr(scene, "folder_parents", {}).get(folder)
            rows.append(dict(uid=layer.uid, name=layer.name, visible=layer.visible,
                             folder_path=path, groups=sum(g.layer == layer.name for g in groups),
                             faces=sum(f.attrs.get("layer", DEFAULT_LAYER) == layer.name
                                       for m in meshes.values() for f in m.faces)))
        return {"layers": rows}

    def _tool_set_layer_visibility(self, uids_or_names, visible):
        if type(visible) is not bool:
            raise ValueError("visible must be a boolean")
        layers = self._viewport.scene.layers
        chosen = []
        for key in uids_or_names:
            matches = [l for l in layers if key in (l.uid, l.name)]
            if not matches:
                raise ValueError(f"unknown layer {key!r}")
            chosen.extend(matches)
        self._viewport.window().layers_dock.panel.set_visible(
            [l.name for l in chosen], visible)
        return self._tool_query_layers()

    def _tool_query_camera(self):
        c = self._viewport.camera
        preset = next((k for k, (y, p) in c._STANDARD_VIEWS.items()
                       if math.isclose(c.yaw, y, abs_tol=1e-8) and math.isclose(c.pitch, p, abs_tol=1e-8)), None)
        return dict(eye=vector(c.eye()), target=vector(c.target), up=vector(c.up_vector()),
                    fov=c.fov_deg, ortho=not c.perspective, preset=preset)

    def _tool_set_camera(self, preset=None, eye=None, target=None, up=None, ortho=None):
        c = self._viewport.camera
        def point(value):
            if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
                raise ValueError("camera vectors must contain three finite numbers")
            return QVector3D(*value)
        e = point(eye) if eye is not None else c.eye()
        t = point(target) if target is not None else c.target
        u = point(up) if up is not None else c.up
        if (t-e).lengthSquared() < 1e-18 or u.lengthSquared() < 1e-18:
            raise ValueError("camera eye/target and up must define a direction")
        if preset is not None and preset not in c._STANDARD_VIEWS:
            raise ValueError(f"unknown camera preset {preset!r}")
        if ortho is not None and type(ortho) is not bool:
            raise ValueError("ortho must be a boolean")
        if eye is not None or target is not None:
            c.distance = (t-e).length()
            c.look_from(e, t-e)
        c.up = u
        if preset:
            c.set_view(preset)
        if ortho is not None:
            c.set_projection("parallel" if ortho else "perspective")
        self._viewport.update()
        return self._tool_query_camera()

    def _tool_zoom_to(self, uids=None):
        vp = self._viewport
        if uids is None and not vp.scene.selection:
            vp.window()._on_zoom_extents()
        else:
            rows = [self._find(uid) for uid in uids] if uids is not None else [r for r in self._groups() if r[0] in vp.scene.selection]
            boxes = [b for r in rows if (b := self._group_bounds(*r))]
            if uids is None:
                b = self._tool_query_selection()["bounds"]
                boxes = [b] if b else []
            if boxes:
                lo = QVector3D(*(min(b["min"][i] for b in boxes) for i in range(3)))
                hi = QVector3D(*(max(b["max"][i] for b in boxes) for i in range(3)))
                vp.camera.fit_box(lo, hi)
                vp.update()
        return self._tool_query_camera()
