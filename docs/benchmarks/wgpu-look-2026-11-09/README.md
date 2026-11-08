# R-look — 2026-11-09 (partial implementation)

This is **not look-parity acceptance**. The images use the same document and
camera: OpenGL `Viewport.render_image` on the left, Metal surface readback on
the right, at 1000×700 logical / 2000×1400 physical pixels. No document is saved.
The default GL path has not been changed. GL uses its normal overlays/axes;
Metal has no overlay primitives in this comparison. Models are framed by their
full world bounds; the ride image is not a curated ride-section camera.

Implemented:

- A full-screen sky/ground background using the GL haze factors, corner ramp
  interpolation, unclamped horizon and horizon line. Flat backgrounds work.
  GL has no default ground grid (`viewport.py`: "No grid"). Infinite axes are
  separate overlay work, not added here.
- A fresh display-style payload honoring the viewport override and the
  document's adopted back tint. String `set_style` remains supported.
- GL's fixed light direction `(0.35, 0.25, 1)` and 0.62/0.38 diffuse factors;
  display colors are decoded before writing to the sRGB Metal surface.
  Cofactor normal transforms handle nonuniform instance scaling.
- Scene bake calls the existing angle-weighted soft-edge fan kernel. Hard
  corners remain faceted; a Rust test checks soft, hard and hidden-only edges.
- 4× MSAA for color and its own depth attachment. Existing single-sample ID
  rendering and picking are retained, followed by a color replay. This doubles
  geometry submission and adds 32 bytes per physical pixel in MSAA attachments
  (89.6 MB at 2000×1400), outside the existing `gpu_memory` buffer counter.
- `read_pixels()` renders and returns tightly packed RGBA. It waits for the GPU
  and must stay out of timed loops. The existing capture API is retained.

Known differences / unfinished deliverables:

- Screen-space edge quads, width controls, profiles/silhouettes, and dashed
  hidden edges are not implemented. Native hard lines still use the existing
  depth bias and now honor edge color. No edge-expansion test is claimed.
- AO/depth-normal post-processing and Distance are not implemented or timed.
  The payload carries those controls but the renderer does not consume them.
- The scene ABI still lacks distinct back materials and texture coordinates /
  an atlas binding. Textured models exist in these captures. Texture parity is
  unfinished, not an empty-model exemption.
- Unpainted container colors still arrive as the old gray from `wgpu_scene`;
  the shader cannot distinguish that value from an explicitly gray material.
  Warm default color / shaded Front tint parity needs a real paint sentinel.
  Hidden-line and monochrome use the requested front color.
- X-ray retains unsorted transparency and fully visible edges. GL's washed
  occluded edges, profile pass and exact transparency are not reproduced.
- Selection/hover retain the earlier renderer's colors. This change preserves
  their overrides but does not implement GL's selection dots or exact colors.
- Smooth fan reuse is tested, but bit-exact GL bake parity is not established:
  the resident geometry normal path and GL quantization differ.
- Standalone WgpuView diagnostics without a source viewport must explicitly
  call `set_style`; the normal source-viewport integration forwards it each frame.

## Reproduction

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work CARGO_PROFILE_RELEASE_STRIP=none .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_core/Cargo.toml
PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py tests/test_wgpu_style.py
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
.venv-work/bin/python scripts/wgpu_look_compare.py /path/to/model.igz
```

Every GUI subprocess was externally bounded to 240 seconds. The full suite
was invoked once with an initially 900-second outer bound, extended to 30 minutes on the same run. The capture script extracts
textures into `.look-tmp/textures` inside this checkout.

The ordinary renderer release build succeeded but failed to import on this
macOS with `mis-aligned LINKEDIT string pool`. Neither stripping nor the classic
linker helped. `CARGO_PROFILE_RELEASE_STRIP=none` produced a loadable extension.
See [Rust issue 157750](https://github.com/rust-lang/rust/issues/157750).

## Measurement limits

The JSON files contain medians over 35 frames after ten warm-up frames, at 2×
HiDPI. GPU values span compute through color resolve (excluding the first background
and the final overlay), come from the asynchronous timestamp ring, and may
refer to earlier frames. CPU values include surface acquisition; unpaced
loops show large acquisition variance. These are whole-frame on/off samples,
not isolated per-pass timings. Do not subtract CPU medians to estimate pass
cost. Capture and GL rendering are outside timed samples. Background and
smoothing have no on/off benchmark; AO and profiles have no implementation.
RGB MAE includes the large matching background and is not a visual acceptance
criterion. In particular, a low whole-image MAE hides missing material detail.

## Captures and frame costs

| Ride at 2000×1400 | CPU median ms | GPU median ms | Wall median ms |
|---|---:|---:|---:|
| msaa=False,edges=False | 9.07 | 6.89 | 9.24 |
| msaa=False,edges=True | 9.24 | 11.55 | 9.49 |
| msaa=True,edges=False | 13.21 | 13.63 | 13.43 |
| msaa=True,edges=True | 19.54 | 19.62 | 19.76 |
| AO / profiles | Not implemented | Not measured | Not measured |


- [pusher_car_rust comparison](pusher_car_rust-comparison.png), RGB MAE 2.361/255; [GL](pusher_car_rust-gl.png), [wgpu](pusher_car_rust-wgpu.png), [timings](pusher_car_rust.json).
- [marquee comparison](marquee-comparison.png), RGB MAE 1.018/255; [GL](marquee-gl.png), [wgpu](marquee-wgpu.png), [timings](marquee.json).
- [space_asbuilt_ride comparison](space_asbuilt_ride-comparison.png), RGB MAE 2.452/255; [GL](space_asbuilt_ride-gl.png), [wgpu](space_asbuilt_ride-wgpu.png), [timings](space_asbuilt_ride.json).

The ride additionally shows a large plane in Metal that is absent in GL,
consistent with the resident path lacking full visibility/section parity.
This capture is evidence of a remaining correctness gap.

## Focused validation

- Core Rust: 5 passed, including soft/hard/hidden-edge normal selection.
- Renderer Rust: 5 passed, including real Metal background/MSAA pipeline validation.
- Offscreen Python scene/style tests: 21 passed.
- Release builds of both crates succeeded; renderer import requires the strip workaround above.
- Native captures of all three documents completed within their 240-second bounds.

## Display-mode and horizon captures

- [hidden_line](pusher_car_rust-hidden_line-comparison.png), RGB MAE 0.654/255.
- [monochrome](pusher_car_rust-monochrome-comparison.png), RGB MAE 2.398/255.
- [wireframe](pusher_car_rust-wireframe-comparison.png), RGB MAE 0.960/255.
- [xray](pusher_car_rust-xray-comparison.png), RGB MAE 10.955/255.
- [shaded-pitch5.0](pusher_car_rust-shaded-pitch5.0-comparison.png), RGB MAE 0.950/255.

Reproduce with `--mode hidden_line --capture-only` (or another mode); use
`--mode shaded --pitch 5 --capture-only` for the on-screen horizon. These runs
do not collect timing samples. The captured GL X-ray path itself shows
substantial overlap artifacts; it is preserved as observed, not retouched.

## Bounded full-suite result

The suite was launched once. Five of six batches completed: **6,136 passed,
19 failed, 115 skipped, 2 xfailed, 804 deselected**. The 19 observed failures
match the supplied baseline by name: 14 translation cases, cached cursor
pick, extension preview wrapping, hidden-panel retention, swatch tooltip
colors and toolbar bold names. No additional failure was observed in those
five batches.

Batch six remained active at the extended approximately 30-minute bound and
was terminated along with this run's own driver. **Full-suite regression
status remains unverified**; these are completed-batch counts, not full-suite
totals. No second suite run was started. See [validation.json](validation.json)
for per-batch summaries and focused-test counts.
