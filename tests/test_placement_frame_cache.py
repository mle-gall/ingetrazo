"""Opening must retain placement bounds for the first interaction."""
from types import SimpleNamespace
from PySide6.QtGui import QMatrix4x4
from core.group import Group
from core.mesh import Mesh
from views.viewport import Viewport


def test_bounds_survive_before_instance_pool_is_published(monkeypatch):
    import views.viewport as module
    monkeypatch.setattr(module, '_paint_of', lambda *_: None)
    groups = [Group(Mesh(), str(i)) for i in range(600)]
    for i, group in enumerate(groups):
        group.xform = QMatrix4x4()
        group.xform.translate(i, 0, 0)
    base = {'uid': 1, 'bbox': ((0, 0, 0), (1, 1, 1))}
    vp = SimpleNamespace(scene=SimpleNamespace(groups=groups),
                         _placements_memo=(None, groups),
                         _proto_base_chunk=lambda *_: base)
    first = [Viewport._placement_frame(vp, g) for g in groups]
    assert len(vp._placement_frames) == len(groups)
    assert all(Viewport._placement_frame(vp, g) is frame
               for g, frame in zip(groups, first))
    groups[0].xform.translate(2, 0, 0)
    moved = Viewport._placement_frame(vp, groups[0])
    assert moved is not first[0]
    assert moved[0] == ((2, 0, 0), (3, 1, 1))
    base['uid'] = 2
    assert Viewport._placement_frame(vp, groups[1]) is not first[1]
