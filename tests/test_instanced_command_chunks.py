"""A visibility change rebuilds only the affected command runs."""
from types import SimpleNamespace
from views.viewport import Viewport, _InstanceBatch


def test_unchanged_runs_are_reused_without_reordering_draws():
    vp = SimpleNamespace()
    batches = {}
    for i in range(64):
        b = _InstanceBatch([object()])
        b.draw_bucket = i // 16
        batches[i] = (object(), None, b, False)
    before = Viewport._inst_draw_chunks(vp, batches)
    assert len(before) == 4
    changed = dict(batches)
    b = _InstanceBatch([object()]); b.draw_bucket = 0
    changed[0] = (batches[0][0], None, b, False)
    after = Viewport._inst_draw_chunks(vp, changed)
    assert after[0] is not before[0]
    assert all(after[i] is before[i] for i in range(1, 4))
    assert [k for chunk in after for k in chunk] == list(changed)
    assert Viewport._inst_draw_chunks(vp, changed) is after
    # First-visible placement ordering can interleave buckets: don't group
    # them out of order (coplanar faces still have their original ordering).
    interleaved = {k: changed[k] for k in [0, 16, 1, 17, 32]}
    got = Viewport._inst_draw_chunks(vp, interleaved)
    assert [k for chunk in got for k in chunk] == list(interleaved)
