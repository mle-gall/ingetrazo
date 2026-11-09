"""Transient UV preview: bake one prototype, replace only its material stream."""
from time import perf_counter

import numpy as np

from core.group import Group
from core.scene import Scene
from views.wgpu_scene import pack_scene


class TexturePreview:
    def __init__(self, view):
        self.view = view
        self.signature = None
        self.original = None
        self.code = None
        self.overlay_only = False
        self.samples_ms = []

    def update(self, tool):
        if not tool.active:
            self.restore()
            return
        texture = tool.result_texture()
        signature = (id(tool.face), tool.side, repr(texture))
        if signature == self.signature:
            return
        if self.overlay_only and tool._drag is not None:
            return
        view = self.view
        tracker = getattr(view, '_instance_updates', None)
        if tracker is None or view.renderer is None:
            return
        mesh = view.scene.mesh
        entry = tracker.meshes.get(id(mesh))
        if entry is None or entry[2] < 0:
            return
        start = perf_counter()
        scene = Scene(groups=[Group(mesh)])
        if self.original is None:
            self.code = entry[2]
            self.original = self._materials(pack_scene(scene, texture_images=False))
        own = dict(tool.face.attrs)
        if tool.side == 'back':
            own['back'] = dict(own.get('back') or {}, texture=texture)
        else:
            own['texture'] = texture
        baked = pack_scene(scene, face_overrides={id(tool.face): own}, texture_images=False)
        view.renderer.update_prototype_materials(self.code, self._materials(baked))
        elapsed = (perf_counter() - start) * 1000
        self.samples_ms.append(elapsed)
        self.overlay_only |= elapsed > 30
        self.signature = signature

    def _materials(self, baked):
        code = int(baked.instances['info'][0, 0])
        header = baked.materials.view(np.uint32).reshape(-1, 4)[code]
        first, length = int(header[1]), int(header[2])
        result = baked.materials[first*16:first*16+length*32].copy()
        if length:
            paths = self.view.packed.texture_paths
            mapping = np.array([0] + [paths.index(p)+1 for p in baked.texture_paths], np.uint32)
            words = result.view(np.uint32).reshape(-1, 8)
            words[:, 5:7] = mapping[words[:, 5:7]]
        return result

    def restore(self):
        if self.original is not None and self.view.renderer is not None:
            self.view.renderer.update_prototype_materials(self.code, self.original)
        self.original = None
        self.signature = None
        self.overlay_only = False
