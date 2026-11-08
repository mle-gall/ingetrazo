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

## Perf 2 — ride viewport telemetry (2026-11-08, partial implementation)

The instanced face/edge passes now report submitted prototype batches and
placements, strict-view frustum and subpixel rejects, logical edit-context
batches, actual draw calls (including retained native tape replay), gather
milliseconds, CPU assembly/remainder milliseconds and CPU GL submission
milliseconds. `face_draws` and `edge_draws` separate the two passes. The once-per-
second summary includes the last frame's counters, even for fast frames.
Recording a deferred tape does not count a draw; executing or replaying it does.
The existing guard-band superset can submit placements counted as strict-view
rejects. These are deliberately different counters, not an accounting identity.

`inst_gl_submit` is CPU wall time inside command submission, **not GPU elapsed
query time**. Driver stalls are included. On the general non-tape path it times
draw calls; on the tape path it includes recorded state calls too. `inst_python`
is the instanced pass time less measured submission, so includes uploads,
untimed GL state work and gathering. It must not be interpreted as a Python
profiler's exclusive instruction time. `inst_vbo` counts allocated prototype
vertex/normal/edge/texture/back buffers and matrix buffers, counting shared
mirror geometry once. It excludes textures, framebuffers, consolidated buffers,
VAOs, driver overhead and all host copies; it is a lower bound, not total VRAM.

Measurement uses Python 3.13 and a release Rust build in `.venv-work`. Local
`.perf-runtime/run.py` bounds every GUI child to 240 seconds (the first diagnostic
was 150 seconds). QSettings, writable Qt data, crash logs and drawing/texture
caches are redirected into the worktree. The input document is read only.
The first main-window diagnostic did not reach model paint before its deadline:
stack samples showed eager `prepare_drawing`, geometry prefetch, cache JSON
serialization, and smooth-stream baking. This is separate from `paintGL`.

A real, isolated QOpenGLWidget benchmark loads the same document, restores its
stored camera and bypasses main-window eager preparation/trays. Its first run
loaded in 7.82 s and reported:

```text
frame 88660ms ground=1ms sync=70877ms shadowmap=0ms faces=17254ms edges=515ms cull=0k/0k tris +0k edges
```

The supplied earlier observation was first paint 20.9 s (faces 17.7 s, sync
2.9 s); this run agrees on faces but has much slower cold sync. The bounded
regression suite ran concurrently, so these are contention-affected observations,
not an isolated hardware ceiling measurement. There are 21 root groups; the
91k group count includes their nested placements.

Implementation status: telemetry is the only implemented deliverable in this
section. Progressive bake/upload scheduling, pending bounding-box rendering,
eager/background pick preparation, a hybrid consolidation policy, and its edge
pass counterpart remain unimplemented. No <2 s first-paint, <100 ms hover, or
<100 ms orbit gate is claimed. The scheduler/split regression tests are also still outstanding; a new
camera-reuse regression verifies the existing pick cache contract (below). A renderer migration decision cannot be based
on this partial work: cached native command replay already exists, but the
first-frame eligibility checks and placement bounds still demand prototype
bakes synchronously, and native replay alone does not reduce draw-call count.
A safe progressive change must address those upstream dependencies as well as
uploads, with consistent handling of transparency, mirrored placements, edits,
picking and cache invalidation.

Telemetry-enabled, default-navigation samples (`.perf-after-orbit.log`):

```text
frame 35219ms ... sync=17433ms faces=17329ms edges=453ms ... inst_proto=10040 inst_place=61766 inst_frustum=26117 inst_pixel=2909 inst_batches=10040 inst_draws=19787 face_draws=9987 edge_draws=9800 gather=14310.0ms inst_python=17403.5ms inst_gl_submit=371.8ms inst_vbo=758.1MiB
frame 33ms ... faces=31ms edges=1ms ... inst_proto=11448 inst_place=65995 inst_frustum=24355 inst_pixel=3135 inst_batches=11448 inst_draws=11395 face_draws=11395 edge_draws=0 gather=4.9ms inst_python=5.2ms inst_gl_submit=25.2ms inst_vbo=814.2MiB
frame 1868ms ... faces=1857ms edges=1ms ... inst_proto=11557 inst_place=66312 inst_frustum=24259 inst_pixel=3108 inst_batches=11557 inst_draws=11504 face_draws=11504 edge_draws=0 gather=1525.6ms inst_python=1787.6ms inst_gl_submit=69.3ms inst_vbo=821.4MiB
```

The first sample shows startup assembly rather than GL submission dominating.
The latter two distinguish a reused tape from a changed-visible-set spike.
They also expose an existing behaviour: `_navigation_detail` suppresses edges
while navigating dense assemblies. A 33 ms faces-only frame is **not** evidence
for the requested faces-plus-edges gate. Full-detail diagnostic runs override
that method to return False in the benchmark wrapper only. No rendering policy
was changed in the implementation. Cold sync timing varied markedly as caches
warmed; no speedup is attributed to this instrumentation-only patch.

Focused validation after the telemetry edits:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q \
  tests/test_instanced_telemetry.py tests/test_instanced_gather_pool.py \
  tests/test_instanced_view_superset.py tests/test_identical_prototype_batches.py \
  tests/test_ambient_occlusion.py tests/test_nested_group_edit.py
```

Result: **45 passed, 8 skipped, 2 warnings in 10.83 s**. The new telemetry file
has four tests, covering deferred/immediate/native/merged submission counting
and disjoint strict-view rejection counts on a reused gather result. Existing
offscreen GL-dependent cases remain skipped; the live benchmark supplies GL
execution evidence. Log: `.telemetry-final.log`.

The requested camera-reuse regression now verifies an existing property:
changing yaw, pitch and perspective preserves the lazy bounds table, loose pick
index and Rust InstanceSet by identity. Moving a placement then invalidates
all three. This is not background preparation and does not establish ride-model
hover latency. The repeated context cost still needs a cursor-specific profile;
assuming every camera change rebuilds the whole scene index would be incorrect.

```sh
INGETRAZO_RUST=1 QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q \
  tests/test_lazy_native_snap.py::test_camera_changes_reuse_pick_geometry_until_a_placement_moves
```

Result: **1 passed in 1.12 s** (`.pick-reuse-test.log`).

Full-detail before/after (navigation edge suppression disabled **in the local
benchmark only**, no product setting changed):

```text
before: frame 35868ms ... sync=18261ms faces=17121ms edges=476ms cull=0k/0k tris +0k edges
before orbit: frame 443ms ... faces=135ms edges=302ms cull=0k/0k tris +0k edges
 after: frame 38621ms ... sync=19850ms faces=18309ms edges=458ms ... inst_proto=10040 inst_place=61766 inst_frustum=26117 inst_pixel=2909 inst_batches=10040 inst_draws=19787 face_draws=9987 edge_draws=9800 gather=15036.4ms inst_python=18332.5ms inst_gl_submit=428.4ms inst_vbo=758.1MiB
 after orbit: frame 260ms ... faces=151ms edges=105ms ... inst_proto=11250 inst_place=65745 inst_frustum=24525 inst_pixel=3132 inst_batches=11250 inst_draws=22200 face_draws=11198 edge_draws=11002 gather=19.4ms inst_python=20.0ms inst_gl_submit=231.0ms inst_vbo=806.6MiB
 after spike: frame 5413ms ... faces=4614ms edges=785ms ... inst_proto=11950 inst_place=67138 inst_frustum=22025 inst_pixel=3080 inst_batches=11950 inst_draws=23577 face_draws=11896 edge_draws=11681 gather=1993.4ms inst_python=4657.1ms inst_gl_submit=735.9ms inst_vbo=830.2MiB
```

Before: 21 logged orbit samples, median 295 ms, range 56–5,720 ms. With telemetry:
48 logged orbit samples, median 293.5 ms, range 46–5,413 ms. These unequal, short
runs with concurrent tests and cache warming are diagnostics, not a speedup
claim. `frame` logs omit frames below 25 ms; medians describe logged samples,
not an unbiased complete frame distribution. Logs are `.perf-before-detail.log`
and `.perf-after-detail.log`; the local runner/wrapper, stack samples and
`.perf-runtime/results.json` retain the reproduction details. Every GUI child
has exited. The maximum measured prototype VBO lower bound was **830.2 MiB**;
no hybrid memory estimate exists because no hybrid path was implemented.

Assessment: this implementation has not demonstrated any of the three latency gates. At full
detail the current renderer sends roughly 20–24k instanced calls per sampled
frame. Even native replay spends hundreds of milliseconds in submission on
some frames; changing visibility can also trigger seconds of gather/recording.
Moving the same Python loop into Rust alone cannot remove those draw calls.
The next experiment should collapse small prototypes with a bounded memory
budget and preserve chunk culling, then measure again. These observations do
not establish GL 3.3's post-consolidation ceiling and do not justify claiming
that wgpu is either necessary or unnecessary. A decision to migrate now would
be based on the current batching architecture, not on a tested GL 3.3 limit.

Bounded suite (run once):

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

Result: **22 failed, 7,083 passed, 138 skipped, 2 xfailed, 805 deselected,
56 warnings in 1,398 s (six batches)**, recorded in `.bounded-suite.log`.
Nineteen failures match the supplied baseline: 14 translations (including ar),
cursor pick, extension wrapping, hidden-panel lifetime, swatch tooltip and
bold toolbar tooltip. The additional three are source-inspection tests in
`test_nested_group_edit.py`: the process imported the viewport before it was
edited, then `inspect.getsource` read shifted source lines from the edited file.
All three passed in the final fresh-process focused run above (which includes
all 24 tests in that file). No additional unresolved regression was observed.
The bounded suite was not repeated on the final snapshot; the new telemetry
file and camera-reuse case were added after their batch collection and were
validated separately by the exact focused commands above.

Generated drawing/texture caches (~3.3 GiB) were removed after measurement;
benchmark scripts, logs, stack samples and the baseline source snapshot remain
locally under the worktree. Nothing was pushed, and no PR or issue was created.
