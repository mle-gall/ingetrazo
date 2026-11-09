# Resident Metal renderer spike

Build from the worktree root:

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
```

`Renderer` is main-thread-only. Its NSView pointer must remain valid until
renderer destruction; `WgpuView` owns it and drops it on close. wgpu creates
the CAMetalLayer through the raw AppKit handle. Only Metal is enabled at
runtime. The swapchain is sRGB; depth and integer ID attachments are single
sample. There is no Qt image-copy fallback because native presentation passed
the bounded embedding checks on the measured machine.

`set_scene((vertices, indices, bounds, commands), instances)` takes byte buffers.
`views/wgpu_scene.py` defines the little-endian ABI:

- Vertex: position float3, normal float3, rgba8 (28 bytes). Alpha zero means
  unpainted, allowing container tint; it is not transparency in this spike.
- Bounds: padded local minimum and maximum float4 (32 bytes).
- Instance: column-major world float4x4, prototype uint32, packed tint uint32,
  flags uint32, reserved uint32 (80 bytes). Flag bit 0 hides a placement.
- Indexed indirect command: index count, instance count (initially zero),
  first index, signed base vertex, first instance (20 bytes).

Each prototype owns a disjoint survivor range whose capacity is its placement
count. Its command's first instance is the prefix sum of those capacities.
Copying the immutable command template resets counts every frame. One compute
invocation per placement tests eight transformed AABB corners against all six
homogeneous clip planes and a one-physical-pixel extent. Near-eye crossings
skip the size test. Atomic increments compact survivors within each range;
there is no append overflow because each placement writes at most once.
The vertex shader resolves instance index through that survivor array.

The adapter's MULTI_DRAW_INDIRECT feature selects a single multi-draw call;
the fallback loops over indirect commands entirely in Rust. Both paths need
INDIRECT_FIRST_INSTANCE, checked during device creation. There is no CPU
visibility list or Python prototype loop per frame.

`set_camera(view, projection)` accepts Qt/OpenGL column-major matrices; Rust
converts clip depth from [-1,1] to [0,1]. `resize` takes logical dimensions
and scale. `pick` takes physical pixel coordinates, returning the packed
placement index (mapped to uid in Python), or -1 for background/outside.
It copies one R32Uint pixel with 256-byte row alignment and waits for mapping.

`render()` returns CPU encode/submit/present milliseconds and optional GPU
milliseconds spanning compute through raster. Timestamp collection currently
waits every frame; Python also records total wall duration including the wait.
This is conservative measurement instrumentation, not a production pipeline.
Use a timestamp readback ring and several frames in flight in production.
`gpu_memory` counts owned resident buffers; add width × height × 8 for depth
and ID attachments. Swapchain images, driver allocations, upload staging and
CPU scene arrays are excluded. Upload is synchronous and briefly duplicates
packed arrays as Python bytes; reducing this peak is production work.

```sh
.venv-work/bin/python scripts/wgpu_spike.py /path/model.igz --measure
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

The measurement script runs a ten-second, full-circle orbit in a 1000×700
window, then reads one center pixel. Each subprocess should additionally be
bounded by a 240-second timeout (the script's Qt timer only runs after load).
The interactive script also closes after four minutes of event-loop time.
Native GUI runs require macOS's normal Qt platform; only packing tests use
offscreen. `INGETRAZO_WGPU=1` installs a display stand-in for each document in
the real window, disables viewport tools, and rebuilds on scene-version
signals. Its hidden GL viewport still holds document state; this is not a
replacement for the production viewport API.

No textures, transparency sorting, back materials, section planes, X-ray,
selection highlight, edges, sheets, billboards, or painter overlays. Native
Metal presentation needs overlays in wgpu or a separately composited sibling
widget; QPainter must not paint into the CAMetalLayer. Nonuniform transforms
currently use approximate normal transforms. Hidden nested-parent propagation
and per-face layer styles need production parity checks.

All direct dependencies are MIT/Apache-compatible. The complete locked graph
and permissive transitive license exceptions approved for this spike are in
`docs/benchmarks/wgpu-2026-11-08/licenses.txt` (from the repository root).

On the locked wgpu 24 Metal backend, `multi_draw_indexed_indirect` itself loops
over `draw_indexed_primitives_indirect` in Rust (`wgpu-hal/src/metal/command.rs`).
The adapter advertises MULTI_DRAW_INDIRECT, but that is not evidence that this
backend uses a Metal indirect command buffer. The measured CPU cost includes
that native loop. A true ICB path is a later experiment, not a claimed result.

Hidden placements remain resident with flag bit 0 set. Edge-only prototypes
retain bounds, placement IDs and capacity ranges, but have zero face index
count. Geometry counts in the report include both; the optional edge raster
pass is not implemented. This distinction matters when comparing inventory
counts to the number of placements which actually rasterize triangles.

To reproduce the inventory separately from rendering:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/wgpu_spike.py /path/model.igz --inventory-only
```

It counts raw deferred positions/faces/edges without building plans or creating
a device. On the supplied ride file it confirms 76,029 geometric placements;
the 86,757 figure from the brief was not reproduced. See P7 for the complete
inventory and the limits of the comparison.

## R1 development update (2026-11-08)

The historical spike description above remains the baseline. These ABI/API
changes supersede it:

- Upload accepts contiguous NumPy uint8 views, borrowing their storage through
  synchronous buffer creation. No Python `tobytes()` geometry copy is made.
- Commands contain P face commands followed by P hard-edge commands. Each pair
  shares a survivor range and both instance counts are reset/updated together.
- `ingetrazo_core.bake_vertices` uses the existing facegeom kernel and rayon
  across faces; `bake_edges` filters soft/hidden flags and computes local bounds.
  Plan construction, prototype iteration, index generation and final buffer
  concatenation still happen in Python. This is not a completed parallel
  whole-scene bake.
- Four independent map buffers collect timestamps asynchronously. A busy ring
  skips collection; `last_timings()` returns CPU ms, last completed GPU ms and
  acquire/poll ms. GPU values can be stale and belong to earlier frames.
  There is no explicit GPU wait in render. Native surface acquisition can block.
- `set_highlight(indices, hovered_index=None)` updates instance flags.
  `set_overrides(packed_rgba)` sets per-instance overrides (alpha zero disables).
  `set_style` accepts shaded/xray/hidden_line/monochrome/wireframe.
  `set_edges(bool)` controls the edge pass.
- `pick_rect(x0,y0,x1,y1)` returns sorted unique visible placement indices from
  a clamped, half-open physical-pixel rectangle. Like point picking it waits;
  it does not select occluded geometry.
- The current path is single-sample. MSAA, silhouette/profile edges, textures,
  section planes and sorted transparency remain unimplemented. X-ray is
  unsorted alpha blending without face depth writes and with edges on top.
- The stand-in shares the source camera, tracks physical size changes and
  provides a status line. Navigation parity is incomplete: middle/shift-middle
  gestures work, but cursor-anchored pivots, all keyboard navigation, and
  zoom-window behavior still require integration.

Use `scripts/wgpu_r1_smoke.py` for the bounded native API/overlay experiment.
Use `scripts/wgpu_spike.py MODEL --measure --interval 16 [--no-edges]` for
paced measurements; `--interval 0` retains the unpaced spike methodology.
The direct/transitive NumPy dependency licenses are included in licenses.txt.

## R1b whole-scene bake (2026-11-08)

`ingetrazo_core.bake_scene` takes contiguous concatenated position float32,
corner/ring-size/ring-count int64, RGBA uint8 palette, per-face hidden bool,
edge int64 pairs, edge uint8 flags, `(P+1,5)` int64 prefix offsets, and
per-face int64 palette indices. Offset columns address positions, corners,
ring sizes, faces, and edges respectively. Corner and edge indices remain
local to their prototype; palette indices address the concatenated palette.

The returned arrays are vertex bytes, uint32 local indices, float32 padded
AABBs, and uint32 prototype triples `(first_index, face_count, edge_count)`.
Base vertex equals first index because every emitted vertex has one index.
Faces precede edges inside each prototype. `PyArray1::from_vec` transfers
ownership of each Rust allocation to NumPy without copying output storage.
Inputs are borrowed/copied during the synchronous call and must not be mutated
by another thread until it returns. The GIL is released for parallel work.

The count pass retains triangle indices/normals and deduplicated boundary
edges. Prefix offsets partition the final allocations into disjoint mutable
slices; Rayon fills them across meshes without a packed-buffer concatenation.
Deferred source positions/rings are used without welding or constructing a
Plan. Source edge flags are accumulated for duplicate index pairs, and absent
ring boundary edges are appended. Geometrically coincident *distinct* source
indices are intentionally not welded. Built meshes use `arrays_of` once and
append their edge/unused positions for bounds. Legacy `bake_mesh` remains a
parity reference, not the production scene path.

Large resident polygons use an x-sorted bounding-box candidate index for ear
clipping. Candidate filtering preserves the original ear choices and triangle
order. The ordinary GL triangulation keeps its original unindexed path.
`PackedScene.timings` exposes Python handoff, native-call and finishing times,
plus process peak RSS at build completion (bytes on macOS). The spike script
reports first picture both including load and measured from load completion.

## R2 overlay API (2026-11-08)

`set_overlay(width, height, rgba)` borrows a contiguous NumPy uint8 RGBA
image at the surface's exact physical size. Pixels use straight alpha and
sRGB color. The texture is retained and reused until resized, with one upload
per call. A separate fullscreen pass composites after scene rendering,
without changing depth or placement IDs. Clear with a transparent image.
`views.wgpu_overlay` supplies Qt rasterization and the logical-pixel primitive
list. This is an overlay foundation; the stand-in still lacks tool integration.

For explicit diagnostics only, `request_capture()`, then `render()`, then
`take_capture()` returns the presented frame's tightly packed RGBA bytes.
This readback waits for the GPU; never request it in interactive frame timing.
The capture occurs after overlays and before presentation, so it verifies the
surface contents, not OS window stacking. The normal render path does no
capture readback. The surface requires COPY_SRC support for this diagnostic.

Run the externally bounded ride proof using `scripts/wgpu_r2_overlay.py MODEL`.
See the dated R2 section of the performance plan for the captured image and
CPU raster/upload measurements; GPU overlay duration is not yet isolated.

## R2a interaction comparison (2026-11-08)

The opt-in view now owns ID-local hover, shared scene selection and camera
input. Native inference preparation runs on a worker and is retained across
camera changes. See the R2a performance-plan section for measured gates and
remaining integration limits. `Renderer.set_msaa(True)` enables a 4× color
resolve experiment while IDs remain single-sampled; X-ray stays single-sample.
It costs a second scene raster pass and stays off by default after exceeding
the ride's 60 Hz GPU budget. `scripts/wgpu_r2a_measure.py MODEL [--msaa]`
records the comparison; externally bound each run to less than five minutes.

## Compact resident layout (2026-11-09)

The Python upload ABI stays at 28 bytes per vertex. Resident face vertices are
also 28 bytes in every pass (including MSAA and weighted X-ray). Texture lookup
continues through the existing sparse material table; no material index or
adjacency is added to faces. The uploaded index buffer is unchanged.

Edges use one 48-byte storage record per source hard edge or non-coplanar
profile candidate, grouped by prototype. Little-endian offsets:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | float32[3] | endpoint A |
| 12 | float32[3] | endpoint B |
| 24 | float32[3] | adjacent normal 0, doubled for profile-only edges |
| 36 | float32[3] | adjacent normal 1 |

Zero normal 1 marks a boundary. Source hidden/soft flags have already been
filtered by the unchanged bake ABI; the soft flag here marks synthesized
profile candidates. Back/hidden-edge dashes remain style/depth decisions.
Normal 0 has unit length for hard edges and length two for profile-only
candidates. The shader tests squared length > 2 and multiplies by 0.5 to
recover the original normal exactly. This power-of-two flag encoding keeps
float32 classification precision within the 48-byte record budget. Degenerate
zero normals occur only on hard edges; synthesized candidates have a nonzero
first adjacency normal. Coincident source edges retain their individual dash
directions; only synthesized profile candidates are welded by endpoint position.

Commands remain 20-byte rows: P indexed face commands followed by P edge rows.
Edge rows are **non-indexed indirect** arguments in the first 16 bytes:
`(E * 6, visible_placements, first_edge * 6, S)`; the fifth word stores the hard-edge vertex count. A second command template
uses that count when profiles are off, skipping all synthesized candidates.
Empty ranges use vertex count zero. Cull increments edge instance count by one,
while face counts and survivor slots are unchanged. Vertex_index/6 selects the
edge record, and survivors[instance_index] selects its placement. Six procedural
corners form each pixel-width quad. This instances a contiguous prototype quad
range across placements, avoiding the measured Metal overhead of one instance
per edge/placement pair. Edge draws loop at 20-byte offsets because
multi_draw_indirect assumes 16-byte strides.

Face upload drops edge-only tails and rebases face commands. Each prototype's
corner order remains unchanged; set_materials applies the same vertex-base
translation to its sparse header. The public handoff is unchanged.

For in-place replacement, preserve each prototype's edge range and update its
command templates (all edges and hard-only); reset indirect counts before culling. Update material-base
translations if face ranges move.
Placement matrix/flags and survivor layouts are unchanged. AO should consume
28-byte face vertices and the existing face commands, never edge rows.

Culling also writes a separate 16-byte `vec4f` viewpoint per placement, indexed
by the original placement ID. Its xyz is the local camera position (w=1) or
local orthographic direction toward the camera (w=0). The camera uniform is now
96 bytes: VP at 0, existing size/style at 64, world camera position/direction at
80. Compute binding 5 writes viewpoints; edge group 0 binding 4 reads them.
This leaves the 80-byte instance and 48-byte edge records unchanged. A singular
placement stores w=2 and uses the projected-area fallback. Profiles are tested
with two normal dot products in the vertex shader; matrix inversion occurs
once per visible placement in culling, not six times per edge.

## Perf placement cache (2026-11-09)

The cull-to-edge binding now contains 80 bytes per resident placement: the
existing local camera vector at offset 0 and a column-major clip-from-local
matrix at offset 16. Culling writes both only for survivors. All compact-edge
passes read that cached matrix, avoiding a matrix product at each quad corner.
The instance and compact edge upload ABIs remain 80 and 48 bytes respectively.

Cold filled-mode picks now submit a separate cull plus full-resolution face
ID/depth pass, retaining material-alpha rejection. They do not submit color,
AO, edges, overlays or presentation. Wireframe keeps its edge-inclusive path.
The queue can still contain an earlier display frame: this is not an isolated
GPU queue or a guarantee of sub-20-ms end-to-end latency. MSAA's single-sample
AO input pass suppresses color writes and edge replay; resolved edges are
rendered only by the MSAA pass.

## R3c-2a section and resident capture foundation (2026-11-09)

The style uniform now has eight float4 rows (128 bytes). The final row at
byte 112 is the world-space section equation. A zero row disables cutting;
fragments with negative signed distance are discarded, matching GL's
`(-normal, dot(normal, point))` kept half-space with zero tolerance.
Faces, depth/ID, weighted X-ray, MSAA and procedural edge/profile fragments
share this equation. The geometry ABI is unchanged.

`render_image(width, height, view, projection, style)` creates temporary
color/depth/ID, AO, MSAA and transparency resources on the existing device.
It uses the resident scene and material buffers without calling set_scene.
It restores interactive attachments, camera/style uniforms, capture state
and picking scheduling after success or a Python error. Targets and pipelines
are currently allocated per capture. Initial Python capture still needs one
scene upload if the view has never been initialized.

This is partial section parity: cap fills, hatching and thick cut boundaries
are not yet implemented. Saved-frame visibility/tint changes that differ
from the resident scene also need a temporary instance-state path.


## Face-me billboards and drawing axes (2026-11-09)

Instance flag bit 3 marks a face-me placement. Culling omits its edge draw;
the face shader is unlit and retains the alpha cut even under a view tint.
Selection/hover updates preserve this bit. Ordinary geometry is unchanged.
`set_instance_world(ids, float32_matrices)` accepts contiguous column-major
matrices, writes only the named 64-byte matrix fields, preserves every other
instance field, and invalidates picking. Python caches the billboard rows,
base transforms, anchors and normals per scene edit and updates O(billboards)
when the camera changes. Resident inference receives the same turned rows.

Simple sprites have fitted 0..1 affine UV columns on both sides; mesh face-me
placements retain their original geometry and UV mapping. Billboard and ordinary
uses of the same mesh get separate prototypes. Edits of such mixed-use meshes
fall back to scene packing because the older incremental tracker keys by mesh;
orbits never use that fallback. Drag previews also reorient the moved anchor.

`set_axes(frame, spacing, visible)` sends a column-major drawing frame and the
GL distance-scaled dot spacing. Procedural one-pixel quads reproduce the positive
100 km half-axis and 520 short negative dashes. Lines are one physical pixel,
depth-tested, with depth writes disabled and no effect on placement IDs. MSAA
axes draw inside the existing edge pass, before model edges. Single-sample axes
use a small separate pass. No Python image rasterization or upload is involved.
Scene axes visibility, edit-context frames and composer style suppression are
resolved in `views/wgpu_axes.py`, without changing global `core.axes` state.

See `docs/benchmarks/billboards-axes/README.md` for bounded captures, targeted
tests and same-session timing evidence.
