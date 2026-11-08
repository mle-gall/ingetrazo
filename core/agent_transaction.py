# SPDX-License-Identifier: GPL-3.0-or-later
"""Extend recipe snapshots to edits of existing objects made by agent tools."""
from copy import deepcopy

from core.group import iter_placements
from core.history import SnapshotImport


class AgentSnapshot(SnapshotImport):
    """Preserve group identity/sharing while undoing metadata and mesh edits.

    SnapshotImport supplies loose geometry and top-level collection membership.
    Tools also edit existing nested groups and extension records, which are
    outside that import-oriented snapshot.
    """
    def __init__(self, mutate):
        super().__init__(mutate)
        self.extra_before = self.extra_after = None

    @staticmethod
    def capture(scene):
        groups = {g for root in scene.groups + scene.kept_components
                  for g, _ in iter_placements(root)}
        meshes = {g.mesh for g in groups}
        objects = list(groups) + list(scene.layers)
        memo = {id(o): o for o in [*objects, *meshes]}
        def attributes(o):
            return vars(o) if hasattr(o, "__dict__") else {
                k: getattr(o, k) for k in o.__slots__ if hasattr(o, k)}
        attrs = [(o, deepcopy(attributes(o), memo)) for o in objects]
        mesh_states = [(m, m.capture_state()) for m in meshes if m is not scene.mesh]
        fields = {k: deepcopy(getattr(scene, k), memo) for k in (
            "plugin_data", "layer_folders", "folder_parents", "layer_folder_uids",
            "active_layer", "units", "dimension_style", "camera_home", "custom_scales")}
        return attrs, mesh_states, fields

    @staticmethod
    def restore(scene, state):
        attrs, meshes, fields = state
        memo = {id(o): o for o, _ in attrs + meshes}
        memo[id(scene.mesh)] = scene.mesh
        for obj, values in attrs:
            restored = deepcopy(values, memo)
            # Keep child-list references held by extensions alive.
            if isinstance(getattr(obj, "children", None), list):
                obj.children[:] = restored.pop("children", [])
                restored["children"] = obj.children
            if hasattr(obj, "__dict__"):
                vars(obj).clear()
                vars(obj).update(restored)
            else:
                for key, value in restored.items():
                    setattr(obj, key, value)
        for mesh, values in meshes:
            mesh.restore_state(values)
        for name, value in fields.items():
            restored = deepcopy(value, memo)
            current = getattr(scene, name)
            if isinstance(current, dict):
                current.clear()
                current.update(restored)
            elif isinstance(current, list):
                current[:] = restored
            else:
                setattr(scene, name, restored)

    @property
    def changed(self):
        return super().changed or self.extra_before != self.extra_after

    def do(self, scene):
        if self.extra_after is not None:
            super().do(scene)
            self.restore(scene, self.extra_after)
            return
        self.extra_before = self.capture(scene)
        try:
            super().do(scene)
            self.extra_after = self.capture(scene)
        except BaseException:
            self.restore(scene, self.extra_before)
            raise

    def undo(self, scene):
        super().undo(scene)
        self.restore(scene, self.extra_before)
