"""Selecting and revealing edges must preserve deferred imported meshes."""
import pytest
from PySide6.QtGui import QMatrix4x4
from core import _native
from core.mesh import Mesh, DeferredMesh
from core.group import Group
from core.scene import Scene
from formats import igz
from tests.test_rendering_surface_regressions import viewport
from tests.test_viewport_smooth_shading import _cylinder


def test_overlay_buffers_do_not_expand_lazy_mesh_or_follow_unrelated_edits(viewport, tmp_path, monkeypatch):
    native=_native.available()
    if native is None or _native.qt_hypot() is None:
        pytest.skip('native array renderer required')
    monkeypatch.setattr(_native,'wanted',lambda:True)
    monkeypatch.setattr(_native,'native',native)
    monkeypatch.setattr(igz,'_LARGE_DOCUMENT',0)
    monkeypatch.setattr(igz,'_BULK_MIN',1)
    source=Scene();g=Group(_cylinder(Mesh()),'tube');g.xform=QMatrix4x4()
    source.groups.append(g)
    path=tmp_path/'tube.igz';igz.save_scene(source,path)
    loaded=Scene();igz.load_into(loaded,path)
    mesh=loaded.groups[0].mesh
    assert type(mesh) is DeferredMesh
    vp=viewport;vp.scene.groups.extend(loaded.groups);vp.scene.version+=1
    vp.makeCurrent()
    try:
        first={kind:vp._hidden_edge_draw(mesh,kind) for kind in ('visible','hidden','selected_hidden')}
        assert type(mesh) is DeferredMesh
        vp.scene.version+=1 # edit elsewhere, not this prototype
        for kind,entry in first.items():
            assert vp._hidden_edge_draw(mesh,kind) is entry
        assert type(mesh) is DeferredMesh
    finally:vp.doneCurrent()


def test_edit_surroundings_keep_original_instance_batch(viewport):
    from views.viewport import _InstanceBatch
    from types import SimpleNamespace
    vp=viewport
    subject=Group(Mesh(),'open')
    vp.scene.edit_group=subject
    vp._edit_rest_mode='fade'
    other=Group(Mesh(),'other')
    batch=_InstanceBatch([other])
    parts=vp._instanced_batches(batch)
    assert parts[0][0] is batch
    batch2=_InstanceBatch([subject])
    parts=vp._instanced_batches(batch2)
    assert parts[1][0] is batch2
    vp.scene.edit_group=None


def test_context_reuses_assemblies_sharing_an_empty_container_mesh(viewport):
    vp = viewport
    empty = Mesh()
    opened = Group(empty, 'open')
    other = Group(Mesh(), 'large assembly')
    other.children = [Group(empty, 'empty shared container'),
                      Group(_cylinder(Mesh()), 'unrelated tube')]
    vp.scene.groups.extend([opened, other])
    vp.scene.version += 1
    before = vp._placements_epoch()
    vp.scene.edit_group = opened
    vp.scene.mesh = empty
    vp.scene.version += 1
    after = vp._placements_epoch()
    assert id(other) in vp._epoch_kept_tops(before, after, ctx=True)
    # Actual geometry changes must still invalidate the subtree.
    from PySide6.QtGui import QVector3D
    empty.add_edge(QVector3D(1, 0, 0), QVector3D(2, 0, 0))
    vp.scene.version += 1
    changed = vp._placements_epoch()
    assert id(other) not in vp._epoch_kept_tops(after, changed, ctx=True)
    vp.scene.edit_group = None
