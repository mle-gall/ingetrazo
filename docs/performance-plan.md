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

## P7 — wgpu renderer spike (2026-11-08)

A separate pyo3 `ingetrazo_render.Renderer` now uploads a resident scene,
computes per-placement frustum/one-physical-pixel culling on the GPU, compacts
survivors into bounded per-prototype ranges, and renders indexed indirect
commands. The production GL viewport is unchanged when `INGETRAZO_WGPU` is
unset. Build/run/API details: [renderer README](../rust/ingetrazo_render/README.md).

### Method and coverage

Apple M1 Max, Metal, macOS 27.2 (26B123), Rust 1.90, Python 3.13.12,
PySide6 6.11.3, NumPy 2.5.4, wgpu 24.0.5. Bare 1000×700 logical window;
viewport 1000×673 at 2× (2000×1346 physical). Single-sample depth and integer
ID target, sRGB presentation; MSAA and edges deliberately omitted. Full-circle
orbit over ten seconds, framed to visible bounds. Test processes were suspended
during measurements. These are repeat runs with warm filesystem caches, not a
controlled cold-cache experiment. Earlier load observations varied from 8.1 to
34.1 seconds for ride; track consistently took about 24 seconds.

CPU is acquire/encode/submit/present time, excluding timestamp-map wait.
GPU timestamps span culling through raster, including intervening scheduling.
Wall time includes camera update, Python/Rust crossing and synchronous timestamp
readback. The render method waits every frame for measurement; there is no
production asynchronous timestamp ring yet. Qt timer/event-loop gaps are not
included in individual wall frame samples; total frames are also reported.
Setup/upload includes adapter, device, pipelines and resident upload together;
it is an upper bound for upload alone. First picture is the first rendered
frame after show/processEvents, not an input-to-photon measurement.

**Input discrepancy:** the supplied path currently contains a 141,384,561-byte
archive, not the brief’s 736 MB file. SHA-256 fingerprints of both measured
inputs are recorded in [inputs.json](benchmarks/wgpu-2026-11-08/inputs.json).
The brief also says 86,757 own placements.
A separate read-only inventory of the exact supplied file at this base commit
finds 91,211 groups, 19,013 distinct mesh objects, 3,107 empty mesh objects,
15,906 deferred nonempty prototypes, and **76,029 placements with positions**
(the same count have edges; 70,374 have raw faces). The renderer retains all
76,029 geometric placements, including hidden and edge-only ones; 69,116 are
visible by scene flags before camera culling. Empty containers do not acquire
a GPU row. This is a full geometric-scene measurement, **not a verified
86,757-nonempty-placement benchmark**. No placements were replicated to force
the requested number. Inventory evidence: [JSON](benchmarks/wgpu-2026-11-08/ride-inventory.json).

### Results

Times in milliseconds are **min/average/max**; startup times are seconds.
The earlier GL numbers are supplied measurements, not rerun here, and include
features omitted by this spike. They are directional comparisons, not visual
parity or controlled cold-start comparisons.

| Metric | Existing GL, ride (supplied) | wgpu ride | wgpu track |
| --- | ---: | ---: | ---: |
| Resident geometric placements | 86,757 reported | 76,029 | 19,622 |
| Nonempty prototype meshes | 15,906 | 15,906 | 4,227 |
| Unique uploaded triangles | — | 8,484,592 | 3,445,443 |
| Load, s | ~15 | 8.09 | 24.37 |
| Build from arrays, s | — | 40.89 | 18.44 |
| Device setup + upload, s | — | 0.259 | 0.098 |
| Owned GPU buffers, MiB | — | 783.97 | 317.30 |
| Depth + ID targets, MiB | — | 20.54 | 20.54 |
| CPU submission, ms | — | 0.93/1.16/12.53 | 0.32/1.13/13.90 |
| GPU, ms | — | 5.59/6.70/35.41 | 2.94/5.42/29.72 |
| Total render call, ms | 270–1,200 orbit | 7.81/9.43/98.12 | 4.00/8.16/52.25 |
| Samples in ten-second orbit | — | 1007 | 1106 |
| Center-pixel pick, ms | 9,400 first hover | 1.32 | 1.37 |
| First picture after load, s | 20.9 reported | 41.27 | 18.66 |
| First picture including load, s | — | 49.36 | 43.03 |

Raw results: [ride](benchmarks/wgpu-2026-11-08/ride.json),
[track](benchmarks/wgpu-2026-11-08/track.json). Pick is a single synchronized
pixel read from the most recently rendered ID target; it is not the app's
full hover/snap workflow. Both center picks hit a placement. GPU memory is
bounded by one geometry copy, two command tables, one instance table and one
survivor slot per placement. Numbers exclude swapchain images, driver memory,
staging and CPU arrays. Depth/ID resize with the widget. Byte conversion at
upload temporarily duplicates the packed CPU arrays; this needs improvement.

The M1 Max advertises MULTI_DRAW_INDIRECT, but the locked wgpu Metal backend
implements that API with a Rust loop of `draw_indexed_primitives_indirect`.
There is one wgpu API call, not one native Metal ICB execution. The explicit
non-multi fallback also loops in Rust and was not separately benchmarked.
Neither path has Python per-prototype work during a frame.

### Embedding findings

`INGETRAZO_WGPU=1` installs a per-document native QWidget stand-in in the
real MainWindow stack. The hidden GL viewport retains document state; tools
are disabled. Scene-version signals coalesce resident rebuilds. A bounded
synthetic real-window run verified direct CAMetalLayer presentation, positive
ID picks, 2× scale, resize with docks hidden, and tab switching back to the
same native view. No texture-to-Qt fallback was needed, so its cost is unmeasured.
This check used a triangle, not the full ride scene inside MainWindow.
Cross-monitor scale transitions and prolonged dock/tab stress remain untested.
QPainter overlays cannot paint into this native layer: production needs wgpu
overlay geometry/text or a separately composited transparent sibling widget,
with explicit focus/hit-testing and stacking tests.

### What this establishes, and what remains

**Proceed with a resident wgpu backend.** On this full geometric scene the
average CPU/GPU/wall times are below 16 ms. **Sustained 16 ms is not established:**
GPU and wall maxima exceed it materially. First-picture latency also needs
work: the ride's array preparation is about 41 seconds, slower than the
supplied 20.9-second GL first-paint figure. The shader/layout approach is useful;
the current synchronous preparation and readback scheduling are not production
ready. Initially quadratic face-colour masks were replaced by linear palette
gathering after timed stack traces exposed the stall.

Not implemented: textures, transparency sorting/back materials, section planes,
X-ray, selection highlight, hard/soft edges, sheets, billboards, painter overlays,
or editing-tool integration. Per-face layers and nested hidden-parent behavior
need parity work; normals under nonuniform transforms are approximate. The
spike must remain opt-in. No production viewport rendering path was replaced.

Production priorities: parallel/progressive scene preparation and disk-cache
reuse; zero-copy or chunked upload and memory budgeting; asynchronous timestamp
and pick rings; invalidation/partial instance and geometry updates; robust
surface loss, cross-display HiDPI and teardown; feature/visual parity tests;
then tools, overlays, materials and edges. Investigate Metal ICBs only after
profiling the already-small native submission cost. Estimate: 2–3 engineer-weeks
to harden this foundation, followed by several additional weeks for feature
parity and interaction integration; this is a planning estimate, not a schedule.

Dependency audit: direct dependencies are MIT/Apache-compatible. The user
explicitly accepted permissive ISC, Zlib and CC0 transitive dependencies.
The full locked all-target/build dependency inventory is in
[licenses.txt](benchmarks/wgpu-2026-11-08/licenses.txt). Its complete SPDX
expression set is MIT; Apache-2.0; MIT OR Apache-2.0 (also reverse-order and
slash spellings); (MIT OR Apache-2.0) AND Unicode-3.0; Apache-2.0 WITH
LLVM-exception; MIT OR Apache-2.0 OR Zlib; Zlib OR Apache-2.0 OR MIT;
Unlicense OR MIT; ISC; Zlib; CC0-1.0. No proprietary or incompatible copyleft
dependency was found in the locked graph. IngeTrazo and this crate remain GPL-3.

### Validation and hand-over

- Rust: **4 passed** (`PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml`). Covers six frustum planes, subpixel rejection, mirrored/sheared bounds, survivor compaction/reset and 20-byte indirect layout.
- Focused Python: **7 passed** (`QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py`). Covers ABI sizes, shared prototypes, local/world AABBs, matrix column order, palette colours, offsets, deferred meshes staying deferred, edge-only and hidden placements.
- Required bounded suite, one invocation: `QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'` — **7,093 passed, 19 failed, 138 skipped, 2 xfailed, 805 deselected, 56 warnings**, six batches. Elapsed 1,643 seconds includes pauses during renderer measurements.
- The 19 failures match the supplied baseline: 14 translation completeness failures (including Arabic), cached cursor pick, extension-preview wrapping, hidden panels, swatch tooltip, and late-toolbar bold tooltip. No additional failures or crashes. [Exact failed test IDs](benchmarks/wgpu-2026-11-08/tests.json).
- Native embedding smoke passed with positive ID picks, 2× scale, docks/resize, tab return, and a hidden-tab scene update uploaded on show. Shader creation, native presentation and timestamps exercised on Metal. Python syntax compilation, Rust formatting and `git diff --check` passed.

Branch: `spike/wgpu-renderer`, based on `b4d4e811`. No push, PR, issue or remote
comment was made. Build commands and ABI are in the renderer README linked
above. This spike demonstrates the current authorized input; the input size
and nonempty-placement discrepancy must be resolved before claiming the
brief's exact 86,757-placement result.

## R1 — resident display development (2026-11-08, incomplete)

This work does **not** meet the R1 acceptance criteria yet. It adds native
face packing, hard edges, instance highlight/override APIs, rectangle picking,
five display modes and asynchronous timestamp collection. The default GL
path remains unchanged. Profiles/silhouettes, textures and section planes are
out of scope. Tools remain disabled on the native stand-in.

The native bake lives in ingetrazo_core to reuse facegeom.rs directly and
avoid copying the triangulator. Rayon parallelizes faces within each mesh.
Python still constructs Plans, iterates prototypes, allocates indices and
concatenates buffers. Native edge packing returns bounds, but the scene
assembler still computes its own bounds. Consequently this is not the
requested complete parallel scene bake; startup remains the primary blocker.
Upload now borrows contiguous NumPy buffers instead of duplicating geometry
with tobytes(). Intermediate packing allocations remain.

### Measurements

Same input files and M1 Max as P7; 1000×673 logical, 2× physical. Warm filesystem
caches. Four paced runs use a 16 ms Qt timer; unpaced runs are recorded
separately. GPU timing is the last completed ring sample, potentially repeated;
it is not paired with the CPU frame in the same row. Brief build/test work
overlapped some measurements, so these are exploratory rather than controlled
performance acceptance results. All native subprocesses had a 240 s deadline.

| Startup metric | P7 ride | R1 ride | P7 track | R1 track |
| --- | ---: | ---: | ---: | ---: |
| Load, s | 8.09 | 7.84 | 24.37 | 23.90 |
| Build, s | 40.89 | 38.02 | 18.44 | 18.01 |
| Device + upload, s | 0.259 | 0.336 | 0.098 | 0.119 |
| First picture after load, s | 41.27 | 38.73 | 18.66 | 18.56 |
| Startup process CPU, s (includes load) | — | 63.16 | — | 46.00 |
| Peak process RSS, GiB | — | 4.55 | — | 5.71 |
| Owned buffers, MiB | 783.97 | 974.52 | 317.30 | 352.96 |
| Depth + ID, MiB | 20.54 | 20.54 | 20.54 | 20.54 |

CPU/GPU/render-call milliseconds, min/average/max, single sample:

| Model and passes | CPU | GPU | Render call |
| --- | ---: | ---: | ---: |
| ride, faces + edges | 1.74/2.13/42.17 | 10.41/11.97/16.50 | 1.84/2.25/42.37 |
| ride, faces | 0.98/3.05/41.15 | 5.91/8.65/22.10 | 1.05/3.30/41.31 |
| track, faces + edges | 0.60/2.12/36.91 | 4.08/8.47/13.76 | 0.68/2.39/37.36 |
| track, faces | 0.41/1.62/34.88 | 3.04/6.84/17.38 | 0.52/1.90/35.03 |

The under-10-second target is missed. MSAA 4× is **not implemented or measured**;
integer ID attachment resolution needs a separate picking pass or another
explicit strategy. Edges remain resident when their pass is disabled, so
GPU buffer memory is the same in the with/without-edge comparisons.
Memory excludes swapchain/driver allocations and transient staging.

### Worst frames and timing

The four-slot timestamp ring uses nonblocking polling and map callbacks.
A full ring skips sampling; render never explicitly waits for mapping.
Point/rectangle picking still synchronizes intentionally.

Unpaced ride saw 305.07 ms worst render call (GPU max 31.21 ms). Unpaced track
saw 82.20 ms, with acquisition/polling max 77.96 ms versus GPU max 13.15 ms.
This localizes the track spike to the CPU acquisition/poll phase rather than
culling/raster duration, but does not isolate native acquisition from polling
or prove the cause of the historical 98 ms spike. GC was not instrumented.
At 16 ms pacing, ride's worst call was 42.37 ms. Pacing avoids feeding the
presentation queue continuously; it is not an equivalent throughput comparison
and does not guarantee a nonblocking swapchain. More phase-specific telemetry
and controlled reruns remain necessary.

### Embedding and remaining work

The stand-in shares the document camera, so menu camera changes become visible.
A 33 ms update timer, physical-size checks and status timing line are present.
Middle/shift-middle gestures are supported; cursor-anchored zoom/orbit,
zoom-window, full keyboard navigation and custom edge-style colours still
need parity work. Face material, container colour and view-tint buffers are
separate; per-face by-layer and layer-effect parity remains incomplete.
X-ray uses unsorted 40% alpha faces without depth writes and edges on top.
Highlights use the GL orange selection/light-blue hover colours.

The reproducible native API/overlay check is scripts/wgpu_r1_smoke.py.
The benchmark JSON files are in
[wgpu-r1-2026-11-08](benchmarks/wgpu-r1-2026-11-08/).

The macOS sibling experiment created a transparent native QWidget above the
Metal view and painted a red badge. The captured test pixel was black rather
than red: **the sibling strategy was not validated** (capture limitations
were not independently ruled out). The same native smoke run successfully
rendered all five styles, updated highlights and returned the expected
rectangle ID. For R2, prefer wgpu-drawn overlays provisionally: they share
the scene's compositor and avoid native sibling stacking. A positive
clip-space overlay experiment is still required before accepting that choice.
The failing sibling evidence is retained in smoke.json; it must not be
reported as a successful overlay proof.

### Reproduction and validation

Builds used the worktree's Python 3.13 venv and CARGO_HOME=.cargo-work:

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_core/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

Native unit tests: core 2 passed (concavity/hole triangulation, edge flags/AABB);
renderer 4 passed. Focused Python handoff tests: 11 passed. The requested
cube-with-hole fixture and comprehensive GPU/style regression tests remain
missing. The license audit includes the added BSD NumPy and MIT/Apache
transitive dependencies. No push, PR, issue or external comment was made.

The full-suite environment used a worktree-local TMPDIR whose socket path
exceeds macOS's Unix-domain socket name limit. Three additional failures in
`test_single_instance.py` all occurred at QLocalServer.listen. A direct probe
with that path returned `QLocalServer::listen: Name error`; a focused rerun
using the shorter worktree-local `.r1-tmp` passed **4/4** without code changes.
Use a short local TMPDIR when reproducing the suite. The original full-suite
failure count is retained separately from that successful recheck.

Final bounded suite (one invocation): **22 failed, 7099 passed, 138 skipped, 2 xfailed, 805 deselected, 56 warnings in 1263s (6 batches)**.
The 19 baseline failures are unchanged; the three additional socket
failures and their 4/4 passing focused recheck are described above.
Exact test IDs and counts: [tests.json](benchmarks/wgpu-r1-2026-11-08/tests.json).

## R1b — 2026-11-08: whole-scene resident geometry

The ride build now meets both requested targets on the Apple M1 Max (Metal,
10 CPU cores). The supplied pre-change cProfile measured 50 s packing;
the final-code native-window measurement is 1.790 s packing
and 2.126 s from load completion to first picture. Including the 7.946 s file
load, the first picture was 10.072 s. These are single-run wall measurements,
not statistical distributions. Input files were read only.

| Ride phase | Before (supplied profile) | R1b native-window run |
|---|---:|---:|
| Full scene packing | 50 s | 1.790 s |
| Native face baking | 28.7 s / 19,014 calls | 0.999 s / one whole-scene call |
| Plan construction | 7.8 s | 0; never requested |
| Python handoff, including placement traversal | included above | 0.685 s |
| Instance/bounds finishing | included above | 0.041 s |
| Device setup and upload | 0.3 s | 0.215 s |
| First picture after load | not supplied | 2.126 s |
| Peak process RSS including upload/orbit | not supplied | 4,629,561,344 bytes |

The native-call timing includes input validation/conversion, parallel
triangulation and final-buffer filling. Handoff and finishing do not include
Python local-array teardown (about 0.065 s in this run). The packed inventory
is 76,029 placements, 15,906 prototypes and 8,484,592 triangles.

Implementation:

- One native call consumes concatenated source arrays, per-mesh offsets,
  face attribute indices and a palette. Built meshes use `arrays_of` once.
- No deferred materialisation or Plan construction. Source edge flags and
  missing face-boundary edges are handled in Rust without position welding.
- Rayon schedules prototypes; the count pass retains triangle indices and
  normals. Final packed buffers are filled through disjoint slices, without
  concatenation, and transferred to NumPy through `PyArray1::from_vec`.
- Paint caches use layer and material value signatures; visibility caches use
  layer/hidden state. Edit and navigator filters retain identity-aware checks.
- Profiling revealed a further bottleneck: large concave polygons spent most
  native time scanning every remaining vertex for each ear. An x-sorted
  candidate index bounds these checks in the resident path while preserving
  exact ear choices and triangle order. The ordinary GL path remains unindexed.
- No dependencies were added. The existing NumPy/PyO3/Rayon versions suffice.

Raw native-window reports are in `benchmarks/wgpu-r1b-2026-11-08/`.
Each GUI process is externally bounded with `subprocess.run(..., timeout=240)`;
measurements use the default 16 ms orbit timer and edges enabled.

A second ride run with the RSS-at-build instrumentation, concurrently with
validation/profiling work, measured 2.261 s packing (0.728 s handoff,
1.389 s native, 0.048 s finishing), 0.445 s device/upload, and 2.836 s to
first picture after load. Peak process RSS at build completion was
**3,488,202,752 bytes**. Both ride runs meet the <4 s packing and <10 s
post-load first-picture targets. The latter is explicitly a post-load target;
the second run took 10.919 s including file loading.

Track is a materially different case: inventory found 4,248 meshes, only **2
deferred**, with 4,227 nonempty resident prototypes and 19,622 placements.
Its 3,445,443 triangles must mostly be extracted from existing Python objects.

| Track phase | Local R1 packer | R1b |
|---|---:|---:|
| Load | 26.224 s | 24.081 s |
| Pack | 18.901 s | 12.870 s |
| Python handoff | not separately instrumented | 12.465 s |
| Native call | not separately instrumented | 0.380 s |
| Finish | not separately instrumented | 0.012 s |
| Device/upload | 0.071 s | 0.160 s |
| First picture after load | 19.084 s | 13.159 s |
| First picture including load | 45.307 s | 37.240 s |
| Peak RSS at build completion | not instrumented | 6,024,921,088 bytes |

Track improves from 18.90 to 12.87 s, but does **not** reach the ride target;
its Python extraction remains the limiting work. Profiling led to remapping
built vertices once instead of once per corner, and replacing 2.15 million
per-face NumPy color conversions with one palette operation per mesh. These
local runs overlapped validation work and are not isolated distributions. The raw
reports are retained. Track's resident triangle count matches R1; buffer size
is 369,601,176 versus 370,105,560 bytes because source edge identity is no
longer reconstructed through a welded Plan. Distinct coincident source points
are intentionally retained; welding parity on such inputs is not claimed.

Build and focused validation (worktree-local Python 3.13 environment):

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_core/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py tests/test_face_geometry_native.py
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

Both release builds succeeded. Rust: 4 core tests and 4 renderer tests passed
(0 renderer doctests). Focused Python: 21 passed. After each built-mesh remap/palette
adjustment, the 14 scene-packing tests passed again. Rust tests include exact
indexed/unindexed ear-order comparisons on 81/200/1000-corner concave polygons
with and without holes; Python tests cover reference face bytes/colors,
prototype offsets, hidden/soft edges, mixed deferred/built meshes, one native
call, no Plan/materialisation, and placement visibility/paint parity.

The final-code ride recheck after the built-mesh palette change measured
**1.790 s pack**, split into 0.685 s Python handoff, 0.999 s native call,
0.041 s finishing and approximately 0.065 s local-array teardown. Device
setup/upload took 0.215 s; the first picture was **2.126 s after load**
(10.072 s including 7.946 s loading). Peak RSS at build completion was
**3,766,779,904 bytes**. See `ride-final-code.txt` for the complete report.

The requested bounded full suite was run **once**, in six batches:
**7,105 passed, 19 failed, 138 skipped, 2 xfailed, 805 deselected**, 56 warnings,
1,264 s. All 19 failures match the supplied baseline: 14 translation cases
(including Arabic), cursor pick, extension preview wrapping, hidden panels,
swatch tooltip and toolbar bold text. There were no additional failures.
The batch totals and failure names are in `validation.txt`. The later small
built-mesh remap/palette adjustments were also checked with the focused
14-test packing suite while the full run was in progress. No GL viewport
behavior or expected baseline tests were changed.

## R2 — 2026-11-08: native overlay foundation

The first overlay gate has a positive **GPU surface capture** on macOS/Metal:
[ride plus overlays](benchmarks/wgpu-r2-2026-11-08/overlay-surface.png).
Qt rasterizes logical-pixel primitives into a straight-alpha RGBA image at
physical resolution; wgpu samples an sRGB texture and alpha-composites it in
a separate pass after scene drawing. The ID attachment is untouched.
No native sibling widget is involved.

On the 76,029-placement ride model, at 1000×700 logical / 2000×1400 physical,
120 paced frames measured CPU rasterization plus texture upload at
2.930 / 3.430 / 5.479 ms min/average/max. This excludes GPU compositing time;
it is not the full frame budget. The captured badge pixel is exactly
RGBA (255, 0, 0, 255). JSON and reproduction script:
[overlay.json](benchmarks/wgpu-r2-2026-11-08/overlay.json),
[scripts/wgpu_r2_overlay.py](../scripts/wgpu_r2_overlay.py).
The explicit capture reads the actual swapchain texture after compositing,
before presentation, and waits only when requested. Normal frames do not wait
for capture. Qt's OS window-grab API returned unrelated foreground content,
which was deleted; OS compositor/window-stacking capture is not validated.

The primitive API supports polylines, polygons, rectangles, points, text,
snap glyphs and projected axes. Empty lists clear a previous overlay.
Resize invalidates the texture dimensions; stale-sized overlays are skipped.
The production GL renderer is unchanged. No new Cargo dependencies.

This section records incremental R2 work, not completion of its interaction
or performance gates.
