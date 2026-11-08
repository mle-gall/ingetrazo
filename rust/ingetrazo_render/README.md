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
