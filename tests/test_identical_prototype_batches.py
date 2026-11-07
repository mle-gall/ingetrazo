# SPDX-License-Identifier: GPL-3.0-or-later
"""Identical draw data may share a batch without sharing editing identity."""
import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from views.viewport import Viewport


def test_identical_parts_keep_their_placements_and_split_after_edit():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        parts = []
        for i in range(3):
            mesh = Mesh()
            mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])
            group = Group(mesh, name=f"Separate part {i}")
            group.xform = QMatrix4x4()
            group.xform.translate(i * 3, 0, 0)
            parts.append(group)
        vp.scene.groups = parts
        vp.scene.version += 1
        vp._frame_planes = None
        batches = list(vp._gather_instanced().values())
        assert len(batches) == 1
        batch = batches[0][2]
        assert list(batch) == parts
        assert len({id(g.mesh) for g in parts}) == 3
        np.testing.assert_array_equal(batch.mats[batch.idx],
                                      [g.xform.data() for g in parts])
        # Painting one independently must invalidate the shared draw batch.
        parts[1].material = {"color": [0.9, 0.1, 0.2]}
        vp.scene.version += 1
        batches = list(vp._gather_instanced().values())
        assert sorted(len(b[2]) for b in batches) == [1, 2]
        assert any(list(b[2]) == [parts[1]] for b in batches)
    finally:
        win._saved_version = vp.scene.version
        win._saved_content = vp.scene.content_version
        win.close()


def test_each_gpu_stream_and_mirror_state_distinguishes_batches():
    from types import SimpleNamespace
    base = dict(vcol=b"faces", edges=b"edges", dback=b"backs",
                smooth_vcol=b"normals", by_texture={("tile", 0.8): b"uvs"})
    variants = [dict(base), dict(base)]
    for key in ("vcol", "edges", "dback", "smooth_vcol"):
        variants.append(dict(base, **{key: base[key] + b"different"}))
    variants.append(dict(base, by_texture={("tile", 0.7): b"uvs"}))
    variants.append(dict(base))
    meshes = [object() for _ in variants]
    chunks = dict(zip(meshes, variants))
    protos = [(m, None, i == len(meshes) - 1) for i, m in enumerate(meshes)]
    codes = np.arange(len(protos))
    pool = (None, [], None, None, codes, protos, None, codes)
    vp = SimpleNamespace(_proto_base_chunk=lambda mesh, paint: chunks[mesh])
    result = Viewport._inst_draw_codes(vp, pool)
    assert result[0].tolist() == [0, 0, 1, 2, 3, 4, 5, 6]
    assert Viewport._inst_draw_codes(vp, pool) is result
