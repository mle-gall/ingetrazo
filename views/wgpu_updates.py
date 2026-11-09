"""Diff resident rows and mesh serials without baking record-only edits.

Removed rows are tombstones: selections and GPU pick IDs never shift. A batch
of mutated prototypes uses one R1b bake; transform previews only write rows.
"""
import numpy as np
from core.group import Group, iter_placements
from core.scene import Scene
from views.wgpu_scene import _placement_state, pack_scene, INSTANCE, COMMAND


class InstanceUpdates:
    def __init__(self, scene, packed):
        self.scene = scene
        self.packed = packed
        self.meshes = {}
        for row, group in enumerate(packed.groups):
            mesh = group.mesh if group is not None else scene.loose_mesh
            self.meshes[id(mesh)] = (mesh, mesh._mut_serial,
                                    int(packed.instances['info'][row, 0]))
        # Empty containers have no GPU row, but still need a serial sentinel.
        all_meshes = [scene.loose_mesh]
        all_meshes.extend(g.mesh for root in scene.groups for g, _ in iter_placements(root))
        for mesh in all_meshes:
            self.meshes.setdefault(id(mesh), (mesh, mesh._mut_serial, -1))
        self.rows = {uid: i for i, uid in enumerate(packed.uids)}
        self.active = set(self.rows)
        self.changed = []
        self.removed = []
        self.version = scene.content_version
        self.pending = set()
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
        hidden = rows['info'][:, 2] != 0
        boxes[hidden, 0] = np.inf
        boxes[hidden, 1] = -np.inf
        return boxes

    def observe(self, history):
        """Use History's existing journal callbacks to avoid scanning known edits."""
        if self.unsubscribe is not None or history is None:
            return
        def before(command, phase, ran):
            if self.scene.content_version != self.version:
                self.journal_valid = False

        def after(command, phase, ran):
            from core.history import (MoveGroupCommand, CompoundCommand, SetRecordCommand,
                                      SetRegistryCommand, InsertGroupCommand, DeleteGroupCommand)
            def visit(command):
                if isinstance(command, CompoundCommand):
                    return all(visit(c) for c in command.commands)
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
        placements = [] if local else [(None, None, False)]
        state = _placement_state(scene)
        loose = self.meshes.get(id(scene.loose_mesh))
        if local and (loose is None or loose[1] != scene.loose_mesh._mut_serial):
            placements.append((None, None, False))
        for root in (self.pending if local else scene.groups):
            hidden = not state(root)[0]
            placements.extend((g, matrix, hidden) for g, matrix in iter_placements(root))
        seen, ids, values, changed = (self.active if local else set()), [], [], {}
        additions = []
        for group, matrix, hidden in placements:
            mesh = group.mesh if group is not None else scene.loose_mesh
            old = self.meshes.get(id(mesh))
            uid = getattr(group, 'uid', 'loose')
            if old is not None and old[2] == -1:
                if old[1] == mesh._mut_serial:
                    continue
                old = None
            if old is None:
                code = len(self.packed.bounds)
                old = (mesh, -1, code)
                self.meshes[id(mesh)] = old
                self.packed.bounds = np.concatenate((self.packed.bounds, np.zeros((1, 2, 4), np.float32)))
                self.packed.commands = np.concatenate((self.packed.commands, np.zeros(1, COMMAND)))
                self.packed.edge_commands = np.concatenate((self.packed.edge_commands, np.zeros(1, COMMAND)))
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
            visible, paint = state(group)
            value['info'][:3] = (old[2], paint, hidden or not visible)
            if row < len(self.packed.instances):
                value['info'][3] = self.packed.instances['info'][row, 3]
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
            baked = pack_scene(Scene(groups=[Group(mesh, name="Resident prototype") for mesh, _, _ in self.changed]))
            for i, (mesh, _, code) in enumerate(self.changed):
                uid = next((j for j, group in enumerate(baked.groups) if group.mesh is mesh), None)
                if uid is None:
                    face = edge = np.zeros((), COMMAND)
                    bounds = np.zeros((2, 4), np.float32)
                else:
                    prototype = int(baked.instances['info'][uid, 0])
                    face, edge = baked.commands[prototype], baked.edge_commands[prototype]
                    bounds = baked.bounds[prototype]
                start = int(face['base'])
                count = int(face['count'] + edge['count'])
                vertices = baked.vertices[start:start+count]
                indices = baked.indices[start:start+count]
                if renderer is not None:
                    renderer.replace_prototype(code, vertices.view(np.uint8).reshape(-1),
                                               indices.view(np.uint8).reshape(-1),
                                               bounds.view(np.uint8).reshape(-1), int(face['count']))
                offset = len(self.packed.vertices)
                self.packed.vertices = np.concatenate((self.packed.vertices, vertices))
                self.packed.indices = np.concatenate((self.packed.indices, indices))
                self.packed.bounds[code] = bounds
                for target, source in ((self.packed.commands, face), (self.packed.edge_commands, edge)):
                    target[code]['count'] = source['count']
                    target[code]['base'] = offset
                    target[code]['first'] = offset + (int(face['count']) if target is self.packed.edge_commands else 0)
                self.meshes[id(mesh)] = (mesh, mesh._mut_serial, code)
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
