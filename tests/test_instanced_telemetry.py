"""Retained command tapes must report work each time they are submitted.

Recording without execution must not count a draw; a native replay and a
Python replay must count exactly the same calls without requiring OpenGL.
"""
from types import SimpleNamespace

import pytest

from views.viewport import _GlTape


@pytest.fixture
def counters(monkeypatch):
    stats = dict(draws=0, submit_ms=0.0)
    monkeypatch.setattr(_GlTape, 'perf', stats)
    return stats


def test_recording_does_not_count_until_replayed(counters):
    calls = []
    tape = _GlTape(execute=False)
    tape.draw(lambda *args: calls.append(args), 4, 0, 3, 7)
    tape.draw(lambda *args: calls.append(args), 1, 0, 2, 7)
    assert counters['draws'] == 0
    assert calls == []
    tape.replay(None)
    tape.replay(None)
    assert counters['draws'] == 4
    assert len(calls) == 4
    assert counters['submit_ms'] >= 0


def test_immediate_and_native_replay_count_once(counters):
    calls = []
    tape = _GlTape()
    tape.draw(lambda *args: calls.append(args), 4, 0, 3, 2)
    assert counters['draws'] == 1
    native = SimpleNamespace(run=lambda *args: calls.append(args))
    tape.replay(native)
    assert counters['draws'] == 2
    assert len(calls) == 2


def test_merged_replay_counts_draws_not_state_commands(counters):
    import numpy as np
    tapes = [_GlTape(execute=False), _GlTape(execute=False)]
    for tape in tapes:
        tape.gl(lambda *args: None, tape.ENABLE, 1)
        tape.draw(lambda *args: None, 4, 0, 3, 5)
    arrays = [t.array_data() for t in tapes]
    native = SimpleNamespace(run=lambda *args: None)
    _GlTape.submit_native(native, np.concatenate([a[0] for a in arrays]),
                         np.concatenate([a[1] for a in arrays]),
                         sum(t.draw_count for t in tapes))
    assert counters['draws'] == 2


def test_gather_reports_disjoint_strict_rejects_on_cached_frames(monkeypatch):
    import numpy as np
    import views.viewport as module
    from views.viewport import Viewport

    mesh = object()
    scene = SimpleNamespace(mesh=object(), version=1)
    groups = [object(), object(), object()]
    lo = np.array([[-2., 0, 0], [1., 0, 0], [2., 0, 0]])
    hi = lo + 0.1
    pool = ((1, id(scene.mesh)), groups, lo, hi, np.zeros(3, dtype=np.int64),
            [(mesh, None, False)], np.zeros((3, 16)), np.arange(3))
    stats = dict(gather_ms=0., frustum=0, pixel=0)
    vp = SimpleNamespace(
        scene=scene, _inst_pool=pool, _inst_perf=stats, edit_rest_fade=0,
        _placements_epoch=lambda: 1, _inst_draw_codes=lambda p: (p[4], p[5], p[7]),
        _frame_planes=[(1., 0, 0, 0)], _INST_VIEW_MARGIN=0.1, _INST_SUPERSET_MAX=2,
        _instances_in_frustum=Viewport._instances_in_frustum,
        _instances_below_a_pixel=lambda p: np.array([True, True, False]),
        _instanced_batches=lambda batch: [(batch, 0.)])
    monkeypatch.setattr(module, '_PERF', True)
    first = Viewport._gather_instanced(vp)
    assert stats['frustum'] == 1
    # The first placement is also small, but frustum rejection owns it.
    assert stats['pixel'] == 1
    assert stats['placements'] == stats['prototypes'] == stats['batches'] == 1
    assert Viewport._gather_instanced(vp) is first
    assert stats['frustum'] == stats['pixel'] == 1
