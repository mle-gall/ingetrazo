# Performance plan — native-modeller fluidity

*Written 2026-08-25, after the piscina.igz marathon. Owner benchmark
(Marco): "the reference native modeller feels ~2× smoother overall" on the same laptop
(Radeon 780M, Wayland). Goal: close that gap on real project scenes
(200–400k faces) — not on synthetic million-face torture tests.*

## The scoreboard (baseline, measured 2026-08-25)

| Metric | Today | Target |
|---|---|---|
| Paint, clean piscina (283k faces) | 4–22 ms | ≤ 16 ms sustained (60 fps) |
| Paint, 5 hedges (1.2M faces) | 37–40 ms | ≤ 20 ms (instancing + culling) |
| Hover latency (pick+snap, big model) | 25–40 ms | ≤ 10 ms |
| Wheel-zoom gesture start (re-pick) | 25 ms | ≤ 5 ms |
| Cold start to first full paint | ~11 s | ≤ 2 s perceived (progressive) |
| Tile upload hitch during zoom | ~100 ms | none ≥ 33 ms |
| Idle CPU | 0 % ✓ | 0 % (keep watching the 149 % ghost) |

`INGETRAZO_PERF=1` is the measuring stick; every phase lands with its
numbers in the commit message, like the marathon did.

## Why the native modeller feels 2× (honest diagnosis)

1. **Input→photon latency, not raw fps.** Our paints already hit 60 fps
   on clean scenes. What a native modeller does better is the path from gesture
   to frame: their event handling, picking and snapping are native; ours
   cross Python on every mouse move (25–40 ms of hover work before the
   paint even starts). Latency, not throughput, is most of the "2×".
2. **They draw less.** No frustum culling here yet: every chunk is
   submitted every frame even when the camera is inside the house.
3. **Fixed per-frame overhead**: the FBO+blit (forced by the Wayland
   depth bug) plus the QPainter overlay pass cost a few ms that native
   apps don't pay.
4. **Instance geometry is world-baked**: 5 instances of a 230k-face
   hedge = 5× vertex data uploaded and drawn. A native modeller draws one
   definition N times.

## Principles

- **Measure first.** No optimization lands without a before/after from
  the perf log. Phase 0 exists so we stop guessing.
- **Draw less before drawing faster.** Culling and instancing beat any
  library swap.
- **Native code only where the profiler demands it,** as leaf kernels
  behind a stable NumPy-shaped interface — never a rewrite.
- **The Python core is the moat, not the bottleneck to remove.** The
  velocity of this project (solo dev + AI pair) exists BECAUSE the app
  is Python. We keep it.

## Phases

### P0 — Frame telemetry (the microscope) — DONE 2026-08-25 (`4a9de47`)
GL timer queries + per-pass timings (faces / edges / silhouettes /
overlay / blit) and an input-to-paint latency stamp, behind a perf HUD
toggle. The perf log gains `frame gl=..ms ovl=..ms py=..ms lat=..ms`.
*Gate: we can name the top 3 costs of any janky frame in one look.*

### P1 — Frustum culling per chunk (draw less) — DONE 2026-08-25 (`4a9de47`)
Every chunk/instance already has (or can cheaply cache) a bbox; cull
against the view frustum before submitting, vectorized over all bboxes
at once (one NumPy pass, ~µs for hundreds of chunks). Also cull the
pick index the same way for hover rays.
*Gate: camera inside the casita → paint cost drops to the visible
subset; orbiting a corner of a big scene never submits the far side.*

### P2 — GPU instancing for components (the hedge killer) — slice 1 LANDED 2026-08-25 (instanced draw all modes + sections; validated live with 5 copies. Remaining: drop baked per-instance pick arrays via ray transform)
Replace world-baked instance chunks with ONE proto VBO + per-instance
matrices via `glDrawArraysInstanced` + `glVertexAttribDivisor`
(GL 3.3 core ✓). Wins: N hedges cost 1× vertex memory and 1 draw; the
instance chunk build (7.3 s cold for 230k) happens once per PROTO;
Move/Rotate of instances updates a 64-byte matrix, not arrays.
*Gate: 5 hedges paint ≈ 1 hedge + ε; cold start no longer rebuilds
per-instance.*

### P3 — Input latency (the feel) — core LANDED 2026-08-25 (ray-pick chunk prefilter: model 41→1.8 ms, sky 34→0.03 ms; budgeted-hover gate shrinks with it. Deferred: FBO depth-readback for the wheel (superseded — pick is ≤2 ms now), overlay dirty-flag)
- Budgeted hover: hard 10 ms budget — pick against the P1-culled index,
  defer the expensive snap refinements to the trailing-edge timer.
- Wheel focus: depth-readback under the cursor (1 px from the existing
  FBO) instead of the 25 ms CPU ray-pick on gesture start.
- Overlay pass on a dirty flag (skip QPainter entirely on pure camera
  frames with no labels in view).
*Gate: hover ≤ 10 ms on piscina; zoom gesture start indistinguishable
from mid-burst.*

### P4 — Async the stalls — LANDED 2026-08-25 (disk chunk cache: hedge 8.5→0.47 s, scene chunks ~7-8→~1.5 s warm; tile uploads paced 6→2/frame. Remaining: the .igz parse itself (~8 s) is now the cold-open floor)
- Tile/texture uploads staged through PBOs or split across frames
  (≤ 2 ms of upload per frame) — kills the 100 ms zoom hitch.
- Progressive cold start: paint what is chunked, build remaining group
  chunks in a background pass between frames (NumPy releases the GIL
  for the heavy slices) — the app is interactive in ~2 s, the hedge
  pops in when ready.
*Gate: no frame ≥ 33 ms during tile churn; time-to-interactive ≤ 2 s.*

### P5 — Native leaf kernels (only where P0 still complains)
Ranked candidates, each a drop-in behind an existing function:
1. **Triangulation**: swap `core/triangulate.py`'s Python earcut port
   for the official C++ `mapbox_earcut` wheel (pip, all platforms, no
   toolchain) — keep ours as fallback and for the hole-splitting
   preprocessing. Cheapest native win available.
2. **Ray/pick BVH**: a small Rust (PyO3/maturin) or pybind11 module for
   triangle BVH build + query. Only if P1+P3 leave picking on top.
3. **Weld/topology bulk ops**: same criterion.
Watch-list, not plan: free-threaded Python 3.14 (chunk builds across
cores once PySide6 supports it cleanly), Qt RHI.

## What we deliberately do NOT do

- **No C++/Rust rewrite of the app or the engine.** Death by rewrite is
  how solo projects end; the leaf-kernel path gets 80 % of the benefit.
- **No renderer/library swap** (VTK, Qt Quick 3D, ModernGL, wgpu,
  game engines): our draw-call count is already low — the overhead they
  would remove is not where the time goes, and each drags its own
  interaction model that fights the push/pull feel.
- **No LOD/impostor system yet**: culling + instancing must land first;
  billboard impostors for distant vegetation are a later, separate
  conversation (the usual push/pull modellers don't have them either — it
  would be a leapfrog, not parity).

## First P0 findings (2026-08-25, live piscina session)

Slow frames (25–29 ms) are dominated by the **edges pass** (19–22 ms:
271k-face wireframe lines + silhouettes) — a P3-adjacent target.
Gesture latency measured at 30–70 ms. Culling live: 12–25k tris
dropped while orbiting; paints 5–12 ms.

## Order and sizing

P0 is half a session. P1 and P3 are a session each and pay the most
"feel" per line. P2 is the big one (touches chunks, picks, move/rotate
paths) — a full session with the regression suite as the net. P4 rides
wherever the telemetry points. P5 only on evidence.

## P6 — array geometry for takeoff and export (2026-11-08)

`core.geometry_arrays` reads deferred Plans directly and caches built-mesh
extraction by mutation serial. Owned placements exclude tagged descendants and
opening groups. Their world positions are welded before ring-edge occurrence
counting, so separately placed open pieces can form one watertight object.
Newell vectors measure gross/net area and anchored float64 volume; hole winding
is normalized for the volume sum to match triangulation's treatment of holes.

Takeoff, class quantities, CSV, the BIM tray, spatial bodies and openings now
consume arrays. Face tags inside group definitions also stay deferred, including
persistent IFC identity updates. Only legacy scene-level loose-face objects
retain the face-based quantity path. Existing explicit face consumers are
unchanged. IFC material weighting reads face metadata in face order without
constructing faces. The default remains BRep; an export profile can select
`"geometry": "polygonal"` for IFC4 or IFC4X3_ADD2. Polygonal bodies contain one
point list and face set, with indexed faces and indexed faces with voids.

Reproduce with Python 3.13, NumPy 2.5.4, PySide6 6.11.3 and ifcopenshell
0.9.0.post1, without the Rust wheel:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/benchmark_array_geometry.py \
  /Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz \
  --output .array-benchmark
```

The input is read-only; outputs go to the worktree. The run found 1,482 tagged
objects and retained all 15,906 deferred group meshes after each export. Baseline
numbers below are the supplied earlier measurements, not a rerun that would
materialize the entire model. The new run overlapped the bounded test suite;
wall times are subject to contention (cold runs ranged from 45.9 to 86.0 s).

| Operation | Earlier Python-face path | Arrays |
| --- | ---: | ---: |
| Load | approximately 10–16 s | 14.95 s |
| Cold takeoff | 951 s | 85.97 s |
| Warm takeoff, no memo | — | 54.82 s |
| Unchanged-scene memo takeoff | — | 0.54 s |
| BRep export (including takeoff) | 781 s | 153.61 s |
| BRep file | approximately 1.37 GB | 1,367,097,328 bytes |
| Polygonal export (including takeoff) | — | 109.79 s |
| Polygonal file | — | 654,530,304 bytes |

BRep is 5.1× faster than the supplied baseline; polygonal export is 7.1× faster
and produces a file 52.1% smaller than the new BRep. Process peak RSS was
1,954,168,832 bytes after warm takeoff and 11,783,258,112 bytes after BRep.
The two exports share a process, so its polygonal-stage RSS high-water mark
still includes the preceding BRep. BRep's in-memory STEP lines and final text
remain a substantial allocation; this change does not introduce a streaming
STEP writer. `--geometry polygonal` measures that profile in isolation.

A separate fresh process using the same command with `--geometry polygonal`
measured a **5,325,602,816-byte peak RSS**, 110.77 s export time and the identical
654,530,304-byte output. In that run, cold/warm/memo takeoff took
45.87 / 32.93 / 0.30 s, with 3,462,086,656-byte peak RSS before export.
All deferred group meshes remained deferred in both runs.

Cold and non-memoized takeoff remain above five seconds, so
`LIVE_TAKEOFF_LIMIT` stays at 2,000. The array path removes Python geometry
allocation, but NumPy planning, welding, and edge counting are still significant.

Twenty small tagged leaf objects from the ride were compared with the old
Python path (at most 100 faces each). Areas, net areas and volumes agreed within
2e-5 relative / 1e-7 absolute tolerance; maximum observed relative error was
1.805725e-6. Bit-for-bit equality is not promised: Qt's float32 geometry and
NumPy's float64 reductions round differently. Regression cases also cover
holes with either winding, nested transforms, large-coordinate anchored volume,
a closed shell split across placements, open sheets, tagged/excluded children,
cache invalidation, loose-face compatibility, deferred face tags and GUID
persistence, deferred material weighting, and IFC4/IFC4X3_ADD2 readback with
EXPRESS-rule validation for both geometry profiles.

Final focused validation:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest \
  tests/test_geometry_arrays.py tests/test_bim.py \
  tests/test_bim_grouped_tags.py tests/test_bim_reinforcing_bar.py \
  tests/test_ifc_export.py tests/test_ifc_records_export.py \
  tests/test_ifc_vocabulary_relationships.py -q
```

Result: **72 passed, 2 skipped** (30.03 s). The standalone array test file has
17 passing tests, including schema/profile/closure parameter combinations.
The required bounded suite command is:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

Bounded-suite result: **22 failed, 6,917 passed, 303 skipped, 2 xfailed,
805 deselected, 56 warnings in 1,488 s** (six batches, run once).
Nineteen failures match the supplied baseline: 14 translation cases (including
Arabic), cursor picking, extension wrapping, hidden-panel lifetime, swatch tooltip,
and toolbar bold text. Three additional first-batch failures were in
`test_ifc_vocabulary_relationships.py` (both relationship round trips and the child
opening/material fallback). They exposed a local `quantities` name collision in
`save_ifc`; the array quantity import is now aliased. The affected file then
passed all 16 tests, and the final combined focused run passed 72 tests with two
skips. The bounded run was not repeated after that fix; no new failure remains
unaddressed. Local logs are `.bounded-suite.log`, `.validation-final.log`,
`.benchmark-final.log`, `.benchmark-polygonal.log` and `.sample-quantities.log`.
Generated large IFC files were removed after measurement.
