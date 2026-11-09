"""Diff resident rows and mesh serials without baking record-only edits.

Removed rows are tombstones: selections and GPU pick IDs never shift. A batch
of mutated prototypes uses one R1b bake; transform previews only write rows.
"""
import numpy as np
from core.group import Group, iter_placements
from core.scene import Scene
from views.wgpu_scene import (COMMAND, INSTANCE, _baked_paint, _placement_records,
                              _placement_state, pack_scene)


class InstanceUpdates:
    def __init__(self, scene, packed):
        self.scene = scene
        self.packed = packed
        self.meshes = {}
        # The same mesh may have ordinary and face-me prototypes. The legacy
        # incremental bake indexes by mesh alone; repack scene edits in that
        # uncommon case, never camera updates.
        self.billboard_modes = {}
        self.shared_variants = False
        # The replacement API currently accepts visible faces/edges only.
        # Repack hidden streams and inherited paint variants atomically until
        # the renderer supports replacing all four ranges together.
        self.hidden_streams = bool(np.any(packed.hidden_commands['count'])
                                   or np.any(packed.hidden_edge_commands['count']))
        self.parity_repack = (any(key[1] != repr(None) for key in packed.prototype_lookup)
                              or any(g.children for g in scene.groups))
        for row, group in enumerate(packed.groups):
            mesh = group.mesh if group is not None else scene.loose_mesh
            mode = getattr(group, 'billboard', False)
            if id(mesh) in self.billboard_modes and self.billboard_modes[id(mesh)] != mode:
                self.shared_variants = True
            self.billboard_modes[id(mesh)] = mode
            self.meshes[id(mesh)] = (mesh, mesh._mut_serial,
                                    int(packed.instances['info'][row, 0]))
        # Empty containers have no GPU row, but still need a serial sentinel.
        all_meshes = [scene.loose_mesh]
        all_meshes.extend(g.mesh for root in scene.groups for g, _ in iter_placements(root))
        for mesh in all_meshes:
            self.meshes.setdefault(id(mesh), (mesh, mesh._mut_serial, -1))
        self.mesh_revisions = {key: mesh.revision for key, (mesh, _, _) in self.meshes.items()}
        self.rows = {uid: i for i, uid in enumerate(packed.uids)}
        self.active = set(self.rows)
        self.changed = []
        self.removed = []
        self.version = scene.content_version
        self.pending = set()
        self.pending_meshes = set()
        self.pending_materials = set()
        self.pending_removed = set()
        self.journal_valid = True
        self.unsubscribe = None
        self.roots = set(scene.groups)
        self.world_boxes = self._boxes(np.arange(len(packed.instances)))

    def _boxes(self, ids):
        rows = self.packed.instances[ids]
        bounds = self.packed.bounds[rows['info'][:, 0], :, :3]
        matrix = rows['world'].transpose(0, 2, 1)
        center = bounds.mean(axis=1)
        extent = (bounds[:, 1]-bounds[:, 0])*.5
        wc = np.einsum('nij,nj->ni', matrix[:, :3, :3], center)+matrix[:, :3, 3]
        we = np.einsum('nij,nj->ni', abs(matrix[:, :3, :3]), extent)
        boxes = np.stack((wc-we, wc+we), axis=1)
        hidden = (rows['info'][:, 2] & 1) != 0
        boxes[hidden, 0] = np.inf
        boxes[hidden, 1] = -np.inf
        return boxes

    def observe(self, history):
        """Use History's existing journal callbacks to avoid scanning known edits."""
        if self.unsubscribe is not None or history is None:
            return
        from weakref import WeakKeyDictionary
        material_targets = WeakKeyDictionary()

        def before(command, phase, ran):
            if self.scene.content_version != self.version:
                self.journal_valid = False

        def after(command, phase, ran):
            from core.history import (MoveGroupCommand, CompoundCommand, SetRecordCommand,
                                      SetRegistryCommand, InsertGroupCommand, DeleteGroupCommand,
                                      SnapshotMutation, MoveVerticesCommand, AddEdgeCommand,
                                      AddFaceCommand, EraseSelectionCommand, HideCommand, AssignLayerCommand)
            def visit(command):
                from core.history import (SetFaceTextureCommand, SetFaceBackCommand,
                                          SetFaceColorCommand, SetFaceOpacityCommand)
                if isinstance(command, (SetFaceTextureCommand, SetFaceBackCommand,
                                        SetFaceColorCommand, SetFaceOpacityCommand)):
                    # Attribute commands deliberately leave geometry serials alone.
                    target = material_targets.get(command)
                    if target is None:
                        faces = set(command._faces)
                        mesh = self.scene.mesh
                        if not faces.issubset(set(mesh.faces)) or id(mesh) not in self.meshes:
                            return False
                        target = material_targets[command] = id(mesh)
                    # Undo may occur after leaving the group's edit context.
                    self.pending_materials.add(target)
                    return True

                if isinstance(command, (HideCommand, AssignLayerCommand)):
                    entities = command._entities
                    if all(isinstance(entity, Group) for entity in entities):
                        # These commands also dirty all GL chunk revisions.
                        # The command journal tells us only placements changed.
                        self.pending.update(entities if self.roots.issuperset(entities) else self.roots)
                        self.mesh_revisions = {key: mesh.revision
                                               for key, (mesh, _, _) in self.meshes.items()}
                        return True
                    return False
                if isinstance(command, CompoundCommand):
                    return all(visit(c) for c in command.commands)
                if isinstance(command, (SnapshotMutation, MoveVerticesCommand,
                                        AddEdgeCommand, AddFaceCommand, EraseSelectionCommand)):
                    mesh = command._target(self.scene) if isinstance(command, SnapshotMutation) else self.scene.mesh
                    old = self.meshes.get(id(mesh))
                    if old is None or old[2] < 0:
                        return False
                    self.pending_meshes.add(id(mesh))
                    return True
                if isinstance(command, (InsertGroupCommand, DeleteGroupCommand)) and command._owner is self.scene.groups:
                    adding = isinstance(command, InsertGroupCommand) != (phase == 'undo')
                    if adding:
                        self.roots.add(command.group)
                        self.pending.add(command.group)
                        self.pending_removed.discard(command.group)
                    else:
                        self.roots.discard(command.group)
                        self.pending.discard(command.group)
                        self.pending_removed.add(command.group)
                    return True
                if isinstance(command, MoveGroupCommand) and command.group in self.roots:
                    self.pending.add(command.group)
                    return True
                return isinstance(command, (SetRecordCommand, SetRegistryCommand))
            self.journal_valid = self.journal_valid and ran and visit(command)
            self.version = self.scene.content_version
        self.unsubscribe = history.add_listener(before=before, after=after)

    def diff(self, scene):
        """Return changed resident rows, retaining prototype and placement IDs."""
        if scene is not self.scene:
            return None
        local = self.unsubscribe is not None and self.journal_valid and scene.content_version == self.version
        placements = [] if local else [(None, None, None, 0)]
        if not local and self.parity_repack and any(
                mesh.revision != self.mesh_revisions.get(key)
                for key, (mesh, _, _) in self.meshes.items()):
            return None  # attribute-only changes also invalidate baked variants
        state = _placement_state(scene)
        loose = self.meshes.get(id(scene.loose_mesh))
        if local and (loose is None or loose[1] != scene.loose_mesh._mut_serial):
            placements.append((None, None, None, 0))
        from types import SimpleNamespace
        from views.viewport import _paint_of
        vp = SimpleNamespace(scene=scene)
        roots = self.pending if local else scene.groups
        placements.extend(_placement_records(scene, roots, vp, state))
        seen, ids, values, changed = (self.active if local else set()), [], [], {}
        if local:
            changed.update((key, self.meshes[key]) for key in self.pending_meshes
                           if self.meshes[key][0]._mut_serial != self.meshes[key][1])
        changed.update((key, self.meshes[key]) for key in self.pending_materials)
        self.pending_materials.clear()
        self.pending_meshes.clear()
        additions = []
        for group, matrix, proxy, flags in placements:
            mesh = group.mesh if group is not None else scene.loose_mesh
            mode = getattr(group, 'billboard', False)
            key = (id(mesh), repr(_baked_paint(_paint_of(vp, proxy))), mode)
            old = self.meshes.get(id(mesh))
            code = self.packed.prototype_lookup.get(key)
            if old is not None and code is None:
                return None  # new paint or billboard variant
            if old is None and (self.parity_repack or self.shared_variants or key[1] != 'None'):
                return None
            self.billboard_modes[id(mesh)] = mode
            uid = getattr(group, 'uid', 'loose')
            if old is not None and old[2] == -1:
                if old[1] == mesh._mut_serial:
                    continue
                old = None
            if old is None:
                code = len(self.packed.bounds)
                old = (mesh, -1, code)
                self.meshes[id(mesh)] = old
                self.packed.prototype_lookup[key] = code
                self.packed.bounds = np.concatenate((self.packed.bounds, np.zeros((1, 2, 4), np.float32)))
                self.packed.commands = np.concatenate((self.packed.commands, np.zeros(1, COMMAND)))
                self.packed.edge_commands = np.concatenate((self.packed.edge_commands, np.zeros(1, COMMAND)))
                self.packed.hidden_commands = np.concatenate((self.packed.hidden_commands, np.zeros(1, COMMAND)))
                self.packed.hidden_edge_commands = np.concatenate((self.packed.hidden_edge_commands, np.zeros(1, COMMAND)))
            if old[1] != mesh._mut_serial:
                changed[id(mesh)] = old
            row = self.rows.get(uid)
            if row is None:
                row = len(self.packed.instances) + len(additions)
                additions.append((uid, group, row))
            if row < len(self.packed.groups):
                self.packed.groups[row] = group
            seen.add(uid)
            value = np.zeros((), INSTANCE)
            value['world'] = (np.eye(4, dtype=np.float32) if matrix is None
                              else np.asarray(matrix.data(), np.float32).reshape(4, 4))
            _, paint = state(proxy)
            value['info'][:3] = (code, paint, flags | (8 if mode else 0))
            if row < len(self.packed.instances):
                value['info'][3] = self.packed.instances['info'][row, 3]
                value['info'][2] |= self.packed.instances['info'][row, 2] & 192
            if row >= len(self.packed.instances) or value.tobytes() != self.packed.instances[row].tobytes():
                ids.append(row)
                values.append(value)
        removed = []
        if local:
            for root in self.pending_removed:
                for group, _ in iter_placements(root):
                    row = self.rows.get(group.uid)
                    if row is not None:
                        seen.discard(group.uid)
                        removed.append(row)
        self.pending.clear()
        self.pending_removed.clear()
        self.version = scene.content_version
        self.journal_valid = True
        self.roots = set(scene.groups) if not local else self.roots
        if changed and (self.hidden_streams or self.parity_repack or self.shared_variants):
            return None
        for mesh, _, _ in changed.values():
            src = mesh.__dict__.get('_deferred_source')
            if src is not None:
                from views.array_bake import _attrs_table
                hidden_geometry = (any(a.get('hidden') for a in _attrs_table(src))
                                   or (src['flags'] is not None and np.any(src['flags'] & 2)))
            else:
                hidden_geometry = (any(f.attrs.get('hidden') for f in mesh.faces)
                                   or any(e.hidden for e in mesh.edges))
            if hidden_geometry:
                return None
        self.changed = list(changed.values())
        self.removed = removed if local else [self.rows[uid] for uid in self.active - seen]
        self.active = seen
        if additions:
            self.packed.instances = np.concatenate((self.packed.instances, np.zeros(len(additions), INSTANCE)))
            for uid, group, row in additions:
                self.rows[uid] = row
                self.packed.uids.append(uid)
                self.packed.groups.append(group)
        return np.asarray(ids, np.int64), np.asarray(values, dtype=INSTANCE)

    def apply(self, ids, rows, renderer=None):
        if self.changed:
            # A single native bake for the changed set, including shared meshes.
            prototypes = []
            for mesh, _, _ in self.changed:
                prototype = Group(mesh, name="Resident prototype")
                prototype.billboard = self.billboard_modes.get(id(mesh), False)
                prototypes.append(prototype)
            baked = pack_scene(Scene(groups=prototypes))
            from views.wgpu_parity import has_transparency
            if renderer is not None and hasattr(renderer, 'set_material_transparency') and has_transparency(baked):
                renderer.set_material_transparency(True)
            exclusions = dict(self.packed.profile_exclusions)
            paths = list(self.packed.texture_paths)
            for path in baked.texture_paths:
                if path not in paths:
                    paths.append(path)
            texture_map = np.array([0] + [paths.index(path)+1 for path in baked.texture_paths], np.uint32)
            if tuple(paths) != self.packed.texture_paths:
                from views.wgpu_scene import _texture_array
                self.packed.texture_paths = tuple(paths)
                self.packed.textures = _texture_array(paths)
                if renderer is not None:
                    renderer.set_textures(*self.packed.textures)
            for i, (mesh, _, code) in enumerate(self.changed):
                uid = next((j for j, group in enumerate(baked.groups) if group.mesh is mesh), None)
                if uid is None:
                    face = edge = np.zeros((), COMMAND)
                    bounds = np.zeros((2, 4), np.float32)
                else:
                    prototype = int(baked.instances['info'][uid, 0])
                    face, edge = baked.commands[prototype], baked.edge_commands[prototype]
                    bounds = baked.bounds[prototype]
                exclusions[code] = dict(baked.profile_exclusions).get(prototype, []) if uid is not None else []
                start = int(face['base'])
                count = int(face['count'] + edge['count'])
                vertices = baked.vertices[start:start+count]
                indices = baked.indices[start:start+count]
                if renderer is not None:
                    renderer.replace_prototype(code, vertices.view(np.uint8).reshape(-1),
                                               indices.view(np.uint8).reshape(-1),
                                               bounds.view(np.uint8).reshape(-1), int(face['count']))
                if renderer is not None:
                    material = np.empty(0, np.uint8)
                    if uid is not None:
                        header = baked.materials.view(np.uint32).reshape(-1, 4)[prototype]
                        first, length = int(header[1]), int(header[2])
                        if length:
                            material = baked.materials[first*16:first*16+length*32].copy()
                            words = material.view(np.uint32).reshape(-1, 8)
                            words[:, 5:7] = texture_map[words[:, 5:7]]
                        elif header[3] & 1:
                            # Incremental material API takes corner records. Expand
                            # only this edited prototype's compressed matching back.
                            records = np.zeros((int(face['count']), 32), np.uint8)
                            records[:, 16:20] = vertices['color'][:int(face['count'])]
                            material = records.reshape(-1)
                    renderer.update_prototype_materials(code, material)
                offset = len(self.packed.vertices)
                self.packed.vertices = np.concatenate((self.packed.vertices, vertices))
                self.packed.indices = np.concatenate((self.packed.indices, indices))
                self.packed.bounds[code] = bounds
                for target, source in ((self.packed.commands, face), (self.packed.edge_commands, edge)):
                    target[code]['count'] = source['count']
                    target[code]['base'] = offset
                    target[code]['first'] = offset + (int(face['count']) if target is self.packed.edge_commands else 0)
                self.meshes[id(mesh)] = (mesh, mesh._mut_serial, code)
            had_exclusions = bool(self.packed.profile_exclusions)
            self.packed.profile_exclusions = tuple((c, p) for c, p in exclusions.items() if p)
            if renderer is not None and hasattr(renderer, 'set_profile_exclusions') and (had_exclusions or self.packed.profile_exclusions):
                renderer.set_profile_exclusions(self.packed.profile_exclusions)
        if len(ids):
            if renderer is not None:
                renderer.update_instances(ids.tolist(), rows.view(np.uint8).reshape(-1))
            self.packed.instances[ids] = rows
        if self.removed:
            if renderer is not None:
                renderer.remove_instances(self.removed)
            self.packed.instances['info'][self.removed, 2] = 1
        if not len(ids) and not self.changed and not self.removed:
            return
        old_count = len(self.world_boxes)
        if len(self.packed.instances) != old_count or self.changed:
            counts = np.bincount(self.packed.instances['info'][:, 0], minlength=len(self.packed.commands))
            self.packed.commands['start'] = self.packed.edge_commands['start'] = np.cumsum(counts)-counts
            self.packed.hidden_commands['start'] = self.packed.hidden_edge_commands['start'] = np.cumsum(counts)-counts
            extra = np.empty((len(self.packed.instances)-old_count, 2, 3), np.float32)
            extra[:, 0] = np.inf
            extra[:, 1] = -np.inf
            self.world_boxes = np.concatenate((self.world_boxes, extra))
        touched = set(ids.tolist()) | set(self.removed)
        if self.changed:
            codes = [code for _, _, code in self.changed]
            touched.update(np.flatnonzero(np.isin(self.packed.instances['info'][:, 0], codes)).tolist())
        touched = np.asarray(sorted(touched), np.int64)
        if len(touched):
            old = self.world_boxes[touched]
            bounds = self.packed.world_bounds
            reduce = np.any(old[:, 0] == bounds[0]) or np.any(old[:, 1] == bounds[1])
            self.world_boxes[touched] = self._boxes(touched)
            subset = self.world_boxes if reduce else self.world_boxes[touched]
            low, high = subset[:, 0].min(axis=0), subset[:, 1].max(axis=0)
            if not reduce:
                low, high = np.minimum(low, bounds[0]), np.maximum(high, bounds[1])
            self.packed.world_bounds = (np.array([low, high]) if np.isfinite(low).all()
                                        else np.zeros((2, 3)))
