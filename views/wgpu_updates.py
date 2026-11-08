"""Diff resident rows and mesh serials without baking record-only edits.

Removed rows are tombstones: selections and GPU pick IDs never shift. A batch
of mutated prototypes uses one R1b bake; transform previews only write rows.
"""
import numpy as np
from core.group import Group, iter_placements
from core.scene import Scene
from views.wgpu_scene import _placement_state, pack_scene, INSTANCE


class InstanceUpdates:
    def __init__(self, scene, packed):
        self.packed = packed
        self.meshes = {}
        for row, group in enumerate(packed.groups):
            mesh = group.mesh if group is not None else scene.loose_mesh
            self.meshes[id(mesh)] = (mesh, mesh._mut_serial,
                                    int(packed.instances['info'][row, 0]))
        self.rows = {uid: i for i, uid in enumerate(packed.uids)}
        self.active = set(self.rows)
        self.changed = []
        self.removed = []

    def diff(self, scene):
        """Return changed rows; new mesh identities currently require repacking."""
        placements = [(None, None, False)]
        state = _placement_state(scene)
        for root in scene.groups:
            hidden = not state(root)[0]
            placements.extend((g, matrix, hidden) for g, matrix in iter_placements(root))
        seen, ids, values, changed = set(), [], [], {}
        additions = []
        for group, matrix, hidden in placements:
            mesh = group.mesh if group is not None else scene.loose_mesh
            old = self.meshes.get(id(mesh))
            uid = getattr(group, 'uid', 'loose')
            if old is None:
                if group is None and not mesh.vertices and not mesh.faces:
                    continue
                return None
            if old[1] != mesh._mut_serial:
                changed[id(mesh)] = old
            row = self.rows.get(uid)
            if row is None:
                row = len(self.packed.instances) + len(additions)
                additions.append((uid, group, row))
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
        self.changed = list(changed.values())
        self.removed = [self.rows[uid] for uid in self.active - seen]
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
            baked = pack_scene(Scene(groups=[Group(mesh) for mesh, _, _ in self.changed]))
            for i, (mesh, _, code) in enumerate(self.changed):
                face, edge = baked.commands[i], baked.edge_commands[i]
                start = int(face['base'])
                count = int(face['count'] + edge['count'])
                vertices = baked.vertices[start:start+count]
                indices = baked.indices[start:start+count]
                bounds = baked.bounds[i]
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
        counts = np.bincount(self.packed.instances['info'][:, 0], minlength=len(self.packed.commands))
        self.packed.commands['start'] = self.packed.edge_commands['start'] = np.cumsum(counts)-counts
