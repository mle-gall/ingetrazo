# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Run with PYTHONPATH=$PWD python tests/benchmark_mutation_notifications.py.

Compares the pre-hook parent with this checkout; no baseline checkout or
shared environment changes are needed. A 10% allowance avoids treating
scheduler noise as an import regression.
"""
import gc
import statistics
import subprocess
import sys
import time
import types
import numpy as np
from core.mesh import Mesh
source = subprocess.check_output(["git", "show", "bec189c4:core/mesh.py"], text=True)
parent = types.ModuleType("core._parent_mesh_bench")
sys.modules[parent.__name__] = parent
exec(compile(source, "<parent mesh>", "exec"), parent.__dict__)
n = 200000
# Shared vertices retain normal edge incidence while repeated faces keep
# the benchmark's memory bounded alongside the full test suite.
pos = np.tile(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]), (n, 1))
rings = np.full(n, 3)
counts = np.ones(n, dtype=int)
times = {"parent": [], "branch": []}
for _ in range(5):
    for name, cls in (("parent", parent.Mesh), ("branch", Mesh)):
        gc.collect()
        start = time.perf_counter()
        mesh = cls()
        mesh.add_faces_bulk(pos, rings, counts)
        times[name].append(time.perf_counter() - start)
        assert len(mesh.faces) == n
        del mesh
for name, values in times.items():
    print(name, "seconds:", ", ".join(f"{v:.4f}" for v in values),
          "median:", f"{statistics.median(values):.4f}", flush=True)
ratio = statistics.median(times["branch"]) / statistics.median(times["parent"])
print(f"branch/parent: {ratio:.4f}", flush=True)
assert ratio < 1.10, "bulk import regressed by more than timing noise allowance (10%)"
