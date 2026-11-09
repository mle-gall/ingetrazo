"""Camera-facing resident placements; geometry and document transforms stay fixed."""
import numpy as np


def fitted_maps(pos, corners, sizes, counts, maps):
    """Map a sprite's horizontal extent and height to 0..1, on both sides."""
    points = np.asarray(pos)[corners]
    if not len(points):
        return maps
    starts = np.r_[0, np.cumsum(sizes)]
    ring = points[starts[0]:starts[1]]
    normal = np.cross(ring, np.roll(ring, -1, axis=0)).sum(axis=0)
    right = np.array([-normal[1], normal[0], 0.])
    right /= max(np.linalg.norm(right), 1e-30)
    u = points @ right
    low, high = u.min(), u.max()
    bottom, top = points[:, 2].min(), points[:, 2].max()
    if high-low <= 1e-9 or top-bottom <= 1e-9:
        return maps
    mapping = [*(right/(high-low)), -low/(high-low), 0, 0, 1/(top-bottom), -bottom/(top-bottom)]
    maps[:] = mapping * 2
    return maps


class Billboards:
    """Cache world-space anchors/normals once per scene edit, O(figures) per orbit."""
    def __init__(self, packed):
        self.packed = packed
        self.ids = np.array([i for i, g in enumerate(packed.groups)
                             if getattr(g, 'billboard', False)], np.int64)
        self.base = packed.instances['world'][self.ids].copy()
        self.key = None
        self.entries = []
        for row, matrix in zip(self.ids, self.base):
            code = int(packed.instances['info'][row, 0])
            command = packed.commands[code]
            start, count = int(command['base']), int(command['count'])
            points = packed.vertices['pos'][start:start+count].astype(float)
            world = points @ matrix[:3, :3] + matrix[3, :3]
            if not len(world):
                self.entries.append(None)
                continue
            low, high = world.min(axis=0), world.max(axis=0)
            anchor = (low+high)*.5
            anchor[2] = low[2]
            tris = world.reshape(-1, 3, 3)
            normals = np.cross(tris[:, 1]-tris[:, 0], tris[:, 2]-tris[:, 0])
            normal = normals[np.argmax(np.linalg.norm(normals, axis=1)), :2]
            length = np.linalg.norm(normal)
            self.entries.append((anchor, normal / length) if length > 1e-9 else None)

    def restore(self):
        self.packed.instances['world'][self.ids] = self.base

    def update(self, camera, renderer=None, inference=None):
        if not len(self.ids):
            return
        eye = camera.eye()
        key = (*eye.toTuple(), *camera.target.toTuple(), camera.perspective)
        if key == self.key:
            return
        self.key = key
        matrices = self.base.copy()
        for j, entry in enumerate(self.entries):
            if entry is None:
                continue
            anchor, normal = entry
            direction = np.array(eye.toTuple()) - (anchor if camera.perspective else np.array(camera.target.toTuple()))
            direction = direction[:2]
            length = np.linalg.norm(direction)
            if length < 1e-6:
                direction = normal if self.packed.groups[self.ids[j]].billboard == 'mesh' else np.array([1., 0.])
            else:
                direction /= length
            cosine = normal @ direction
            sine = normal[0]*direction[1]-normal[1]*direction[0]
            rotation = np.array([[cosine, -sine, 0.], [sine, cosine, 0.], [0., 0., 1.]])
            turn = np.eye(4)
            turn[:3, :3] = rotation
            turn[:3, 3] = anchor - rotation @ anchor
            matrices[j] = (turn @ self.base[j].T).T
        self.packed.instances['world'][self.ids] = matrices
        if renderer is not None:
            renderer.set_instance_world(self.ids.tolist(), matrices.reshape(-1))
        if inference is not None:
            inference.update(self.ids, self.packed)
