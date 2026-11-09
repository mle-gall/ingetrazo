# R-look 3a — horizon ambient occlusion (2026-11-09)

The Metal pass ports `resources/shaders/ao*.frag`: two horizon directions,
ordered rotations, depth-derived normals with the smaller one-sided depth step,
world-space radius and quantization bias, two plane-aware blur passes, depth-aware
upsampling, and the cubic multi-bounce fit. AO runs after opaque faces and before
edges and overlays. X-ray and wireframe bypass it, as in GL. GL is unchanged.

`ambient_occlusion`, `ao_distance` and `ao_intensity` come from the display style.
The shared GL settings helper also supplies enable/radius/intensity/sample-count environment overrides.
`ao_samples` and `ao_resolution` (1 full, 2 half, default 2) are diagnostic payload
fields. Invalid or nonfinite native parameters are rejected.

MSAA reuses the existing single-sample picking depth for reconstruction. Faces
resolve for the bounce input; the multiplier is applied to the retained 4x colour
attachment, then edges resolve last. AO-off keeps the original combined pass.
No geometry replay is added by AO itself. Targets are allocated lazily and reused
until size or resolution changes; no new dependencies are required.

## Reproduce

Use the worktree's `.venv-work` and native release builds. Each invocation is
bounded to 240 seconds by the capture runner (including load and GUI startup).

```
.venv-work/bin/python scripts/wgpu_ao_compare.py MODEL --ao off --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3a
.venv-work/bin/python scripts/wgpu_ao_compare.py MODEL --ao half --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3a
.venv-work/bin/python scripts/wgpu_ao_compare.py MODEL --ao full --section --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3a
```

Pairs place GL `render_image` on the left and Metal `read_pixels` on the right.
The paired ride section is root 1 (`Groupe#310`, 264 placements), isolated in
memory with `--root-start 1 --root-limit 1 --capture-only`. The complete ride
(76,029 instances) is retained for timing, using `--metal-only --section --matrix`:
the camera distance is one fifth of the full-scene fit. The first whole-ride GL
capture was stopped near its 240-second bound without an image.

The timing matrix cycles all six configurations three times, with 10 warmup and
35 measured frames per configuration per round (105 measured samples), edges enabled. GPU timestamps
span geometry and AO; CPU and wall timings are also retained in the JSON. These
are whole-frame costs, not an isolated AO GPU query. Differences between on/off configurations include system load; other agents
were using this Mac concurrently, so these are samples, not isolated guarantees.

## Integration limits

The current wgpu depth has no GL foliage stencil exclusion. Integration with
textured cutout materials needs an exclusion mask from that agent's material
pass; AO currently treats every depth-writing face alike. Single-sample depth
can differ at MSAA silhouettes. Existing GL/Metal material and lighting differences
also remain in the whole-image pixel difference; it is not an AO-only error metric.


See [comparison images and pixel differences](samples.md) and [ride cost table](costs.md).
The pusher car shows similar soft gradients along its wall/slab junction; GL is
somewhat darker near the mechanical parts. The marquee’s stone textures and the
car’s painted wheels remain different in the base renderers. The narrow ride
section has a small screen-space AO footprint, so its whole-image error is low
and is not by itself evidence of perfect local agreement. GL’s axes remain in
its reference image; Metal captures omit them.

## Validation commands

```
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work CARGO_PROFILE_RELEASE_STRIP=none .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml --lib
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_ao_style.py
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -u scripts/pytest_batches.py -m 'not slow'
```

Both release builds succeeded. Renderer Rust: **8 passed**, including real Metal
execution against synthetic flat and concave depth buffers and pipeline validation
for both sample counts. Focused Python style tests: **2 passed**. Model captures
exercise the split MSAA timestamp path as well as AO itself. Initial shader-mask
and empty-timestamp validation errors were corrected before successful captures.


The single complete offscreen suite finished in **1,903 seconds**, six batches:
**7,146 passed, 18 failed, 142 skipped, 2 xfailed, 805 deselected, 56 warnings**.
All 18 failures match the supplied 19-failure baseline: 14 translations (including
`ar`), cursor pick, extension wrapping, hidden panels and toolbar bold. The
baseline swatch-tooltip failure did not reproduce. **No additional failures**
were observed. The longest batch took 509.81 seconds; none exceeded 30 minutes,
so no split or second full-suite run was needed. See [full suite output](suite.txt)
and [final renderer Rust output](rust-tests.txt).
