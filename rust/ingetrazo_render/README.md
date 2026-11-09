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

## Edit context fade and hide

`set_rest(rows, mode)` uses flag 64 for the rest of the model and flag 128
for edit-hidden rows. It accepts `fade`, `hide`, and `none` (`normal` is the
GL preference alias). Selection, hover, billboard and document visibility
bits survive both this operation and placement updates. A context change
updates the CPU flags in O(placements), then performs one resident-buffer
write; ordinary frames and fade-strength changes never rewrite those flags.
The colour override byte remains reserved for view tints.

The style uniform now contains nine float4 rows (144 bytes): section stays
at byte 112; fade colour RGB and factor occupy byte 128. The face, textured,
unlit billboard, MSAA and X-ray paths share the post-material fade, as do
hard/profile/back edges. Fade does not change alpha or depth behavior.
Edit-hidden rows are rejected before culling counters and survivor insertion,
including in the independent picking pass.

The Python view caches membership for the innermost open group's subtree,
invalidating on repack/placement edits. Live mode/factor come from the GL
viewport. The edit box reuses GL's oriented/padded corners and pixel hull,
with the same physical dash length, colour and one-pixel width. As requested,
the native box is a depth-free overlay (GL depth-tests its scaffold).


## P2 raster parity API (wave 1)

The public vertex/instance/COMMAND ABIs remain 28/80/20 bytes. Section and
edit-fade rows remain at bytes 112 and 128. The style uniform appends a tenth
float4 at byte 144 (160 bytes total): material-opacity opt-in, group-edge-only
selection, hidden-geometry visibility, hidden-object visibility.

`set_style` additionally accepts:

- `material_opacity=False`: opt into the wave-1 alpha ABI. Byte zero means
  unpainted; 1–255 means painted with effective opacity alpha/255. This changes
  the old provenance threshold only when enabled. Byte 254 is no longer a
  two-sided paint marker in this mode. `views.wgpu_style.style_payload` enables
  it for P3 packs. Opaque fragments write depth; partial alpha goes through
  weighted blended OIT against opaque depth with no depth writes, after opaque
  AO. Partial regular texture alpha multiplies material alpha; face-me flag 8
  keeps the hard 0.5 texture cut. Picking retains nonzero-alpha fragments.
  `PackedScene.upload` classifies material/back/texture alpha and calls
  `set_material_transparency(bool)`. Opaque packs skip OIT and its depth resolve
  while retaining the new alpha ABI. Geometry edits conservatively enable OIT
  when introducing transparency; a full repack recomputes classification.
- `group_selection_edges=False`: native default preserves the old marks;
  Python style payload enables it. Group selection/hover retains edge highlights
  and removes face dots. P1 supplies loose-face dots separately with
  `set_face_marks`. Enclosure geometry can use preview edge pairs.
- `show_hidden_geometry=False`, `show_hidden_objects=False`: enable the separate
  uploaded ghost meshes; no ghost upload or render work occurs by default.
- `shadows=False`, `sun_direction=(0,0,1)`, `shadow_darkness=0.55`,
  `ground_shadows=True`, `shadow_matrix=identity`: optional cached 2048² sun
  depth map, bilinear 3×3 PCF, sun-facing illumination, and a z=-0.005 ground
  catcher. Matrix is GL/Qt column-major light VP; Rust converts depth to 0..1.
  `sun_payload` computes GL's geography/date/north and light fit. Invalid dates,
  night, the kill switch, and technical sheet styles disable it. The catcher
  follows the document map/terrain/photo visibility predicates. Reference
  geometry itself still requires P5.

The shadow map includes off-camera casters, ignores hidden/edit-hidden rows,
clips at the section plane, rejects material opacity below 0.7, and reuses the
map while the camera moves. Geometry, transforms, visibility, texture/material,
section and sun changes invalidate it. Sun receivers currently use reconstructed
flat normals from opaque depth, not interpolated smooth normals, and do not
shade translucent receivers. The map is allocated at renderer construction
(16 MiB), but disabled shadows encode no map or receiver pass. Temporary captures
have isolated shadow state. Shadow map GPU time is not separately instrumented;
steady receiver cost is included between face and edge timestamps.

Tool/pack integration APIs (all empty/inactive initially):

- `set_preview_mesh(triangles, edges)`: contiguous uint8 views of world-space
  28-byte vertices; triangle count divisible by 3, edge count by 2. RGB/material
  shading, alpha blending and scene depth testing; opaque preview triangles
  write depth. Pass empty arrays to clear. No texture table is supplied for this
  transient API. Mesh tools upload their preview faces and edges during pointer
  motion and clear them on commit/cancel. Select uses the edge stream for loose
  selected/hovered edges.
- `set_face_marks(triangles)`: same world-space vertex layout; caller supplies
  highlight RGB. Depth-tested 2×2/6px stipple, no depth writes. The view resolves
  editable selected faces through cached prototype triangle ranges and the GL
  contrast-color chooser. Group flags highlight edges only.
- `set_suppressed_faces([(prototype, first_triangle, triangle_count), ...])`:
  indices are local to that prototype's FACE command, not face IDs or source
  vertex offsets. Validates all ranges before writing; makes the triangles
  degenerate in the resident index buffer, affecting color, depth/IDs, AO and
  shadows. `[]` restores the original indices. No scene bake is required.
  The active editable mesh supplies cached face-to-triangle ranges. Suppression
  applies to every placement of a shared prototype; group editing uses the
  scene's existing isolated world copy before a placement-local edit.
  Resend after prototype replacement. New scenes clear transient meshes.
- `set_profile_exclusions([(prototype, xyzxyz_flat_list), ...])`: source soft
  endpoint pairs in prototype space. Converts matching hard records to
  silhouette-only candidates and moves them outside the hard-only indirect
  range, preserving boundary outlines with profiles on. `[]` restores the
  uploaded edge policy. The pack retains source soft/hidden endpoint pairs;
  soft prototypes weld repeated source coordinates for corner-normal fans. Resend after repacking/replacement. Endpoint matching
  is exact float32, consistent with the packed positions.
- `set_hidden_geometry(vertices, indices, hidden_commands,
  hidden_edge_commands, object_rows=[])`: separate original hidden streams,
  one 20-byte COMMAND per prototype for each kind. All arrays are contiguous
  uint8 views. Hidden faces become a 1px/4px grid; hidden edges use 3px dashes.
  `object_rows` names hidden placement IDs without allocating a new instance
  flag bit; those rows also reveal their ordinary resident faces/edges.
  The pack supplies both hidden ranges. Object rows require bit 4 and exclude
  bit 5 / edit-hidden bit 7. The view refreshes after transform/visibility and
  edit-context changes. Neither reveal toggle enabled means no ghost expansion
  or upload; changing the document toggles invalidates the pack.
  The ghost upload expands placement transforms on the CPU, off the ordinary
  frame path. It currently uses vertex colors, not material textures.

MSAA fill now uses face-slope depth bias, and sufficiently long edge joins use
half-pixel caps; subpixel segments retain their original coverage to avoid
inflating dense machinery. Axes use strict depth with a small away bias so
coplanar face-me pixels win. AO bounce uses the GL display-color domain before
converting its multiplier back to linear framebuffer space. X-ray retains GL's
0.6 face opacity and 0.6 hidden-edge fade, and keeps front paint on unpainted
backs instead of averaging in default blue-grey. Weighted OIT overlap remains
an approximation to GL's ordered blend; see the paired evidence for residuals.

Validation and reproducible offscreen evidence are in
`docs/benchmarks/metal-parity/wave1/p2/`. `tests/test_metal_parity_raster.py`
contains a synthetic alpha-byte pack and can wrap the established audit script
to inject pending P3 alpha/soft metadata without modifying production packing.
Native tests use an **unshown Cocoa NSView**; ordinary Qt-offscreen test runs
skip them. There are no live application launches in this package.

### P7 production integration

Material header word 3 bit 0 now means “matching back uses front vertex RGBA”.
It avoids allocating 32-byte per-corner records for an entirely matching-back,
untextured prototype, without sacrificing opacity. Other header bits remain
reserved. Incremental edits expand only the changed prototype when using the
legacy corner-record update API. Core and renderer extensions must be rebuilt
together. This reduces the ride's material stream from 815,977,536 to 255,552
bytes; peak-process RSS is measured separately in the P7 report.

`wgpu_parity.py` owns pack handoffs and editable triangle-range resolution.
`wgpu_annotations.py` is now scheduled in production (including guides-only and
tool-only documents); exports use its output-aspect layout and omit interactive
feedback. Tape/guide/axis/reference and nearby-edge facade paths use resident
inference or shared projection-only GL helpers; Arc continuation queries bounded
resident curve tangents rather than GL placements. No GL pick cache is consulted.
See `docs/benchmarks/metal-parity/wave1/p7/REPORT.md` for actual capture limits,
performance samples, and remaining partial findings.
