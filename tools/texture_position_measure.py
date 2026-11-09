"""Read-only document benchmark; run with a worktree-local texture cache."""
import json
import sys
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QVector3D

from core.scene import Scene
from core.group import iter_placements
from formats.igz import load_into
from tools.texture_position import TexturePositionTool
from tools.texture_position_metal import TexturePreview
from views.wgpu_view import WgpuView


def main(path):
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    load_into(scene, Path(path))
    group, face = next((g, f) for root in scene.groups for g, _ in iter_placements(root)
                       for f in g.mesh.faces if TexturePositionTool.side_texture(f, 'front'))
    scene.begin_group_edit(group)
    view = WgpuView()
    view.resize(1000, 700)
    view.set_scene(scene)
    view.camera.target = face.centroid()
    view.camera.distance = 5
    view.show()
    app.processEvents()
    tool = TexturePositionTool()
    tool.begin(view, face, face.centroid())
    preview = TexturePreview(view)
    samples = []
    try:
        for i in range(10):
            tool.map.R += tool.map.e_u * .01
            start = perf_counter()
            preview.update(tool)
            submitted = perf_counter()
            view.draw_frame()
            view.pick_row(0, 0)
            samples.append({'bake_upload_ms': (submitted-start)*1000,
                            'through_frame_ms': (perf_counter()-start)*1000})
        print(json.dumps({'model': Path(path).name, 'group': group.name,
                          'faces': len(group.mesh.faces), 'placements': len(view.packed.instances),
                          'overlay_only': preview.overlay_only, 'samples': samples}, indent=2))
    finally:
        preview.restore()
        view.close()


if __name__ == '__main__':
    main(sys.argv[1])
