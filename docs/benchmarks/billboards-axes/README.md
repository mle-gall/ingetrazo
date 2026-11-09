# Metal billboards and axes — 2026-11-09

Branch: `renderer/billboards-axes`, based on `39e4fbf1`.
Machine: Apple M1 Max, Python 3.13.12, PySide6 6.11.3, Metal, 2× display scale.

## Implementation

- GPU procedural one-pixel quads for axes use GL's colours, positive 100 km segments, and 520
  negative dots at `distance * .008` spacing and 18% duty. They use one
  physical pixel, read-only depth, and precede model edges. MSAA uses the
  existing edge pass; there is no Python rasterization or full-screen upload.
  The scene toggle, edit-context axes and composer suppression are respected.
- Cached billboard anchors and normals drive column-major world matrices.
  Camera changes write only each billboard's 64 matrix bytes through
  `set_instance_world`; flags, tint, geometry and pick IDs stay resident.
  The same matrices update resident inference. Preview moves, committed moves,
  nested placements, edit contexts and offscreen captures use this path.
- Simple sprites fit UVs to 0..1 on both sides, have no hard/profile edges,
  and render unlit with alpha < .5 discarded. View tint retains alpha rejection.
  Mesh face-me placements rotate their real geometry and preserve existing UVs.
  Ordinary instances sharing the same mesh retain their original mapping/edges.

A shared mesh used as both an ordinary object and a billboard requires a full
pack on **scene edits**, because the pre-existing incremental tracker keys by
mesh. Camera changes always remain O(billboards) with matrix-only writes.

## Visual evidence

Every comparison is **OpenGL left / Metal right**. New-document captures launch
`main.main()` with no model and `--new-window`, close Home, then capture the
actual viewport. The orbit adds 1.2 radians to yaw. GL uses its framebuffer;
Metal uses the renderer's native pixel readback. Captures are outside timing.
All PNGs are at most 1400 pixels wide and below 1 MB.

| View | Before | After |
| --- | --- | --- |
| New document, default | [before-default-comparison.png](before-default-comparison.png) | [after-default-comparison.png](after-default-comparison.png) |
| New document, orbit | [before-orbit-comparison.png](before-orbit-comparison.png) | [after-orbit-comparison.png](after-orbit-comparison.png) |
| Ride, matched fitted camera | — | [space_asbuilt_ride-comparison.png](space_asbuilt_ride-comparison.png) |

Individual captures: `gl-default.png`, `gl-orbit.png`, `before-default.png`,
`before-orbit.png`, `after-default.png`, `after-orbit.png`,
`space_asbuilt_ride-gl.png`, `space_asbuilt_ride-wgpu.png`.

Visual inspection confirms one complete camera-facing Engineer, no quad outline
or visible mip halo, and matching axis origins, colours and negative dots in
both default and orbited views. The ride comparison shows no visible regression
at this camera. This is a visual comparison, not a pixel-identical rendering claim.

## Verification

The real-app harness asserts GPU selection, Move preview and commit, surface
inference on the turned quad, view tint, and entering/leaving the figure edit
context: [interaction.json](interaction.json).

The targeted Python tests cover fitted mapping and ordinary shared prototypes,
mesh face-me mapping, perspective and parallel camera turns, nested placements
against GL's quad, edit contexts, tint/visibility flags, inference and axes state.
The Rust test constructs both sample-count pipelines on Metal. Full-suite testing
is deliberately left to the parent. All builds use release; no debug target was
created. No push, PR, issue or comment was made.

- Python: **188 passed** across `tests/test_wgpu*.py` and the existing
  `tests/test_scale_figure*.py` files; no `test_billboard*.py` files exist.
- Rust, release only: `axes_validate_on_metal_at_both_sample_counts` and
  `row_updates_preserve_selection_and_hover` passed.
- A test also checks that blanking the viewport clears old billboard row IDs.
- Existing QImage.mirrored deprecation warnings remain.

## Frame cost

`ride-before.json` and `ride-after.json` are same-work-session runs of the
existing `scripts/wgpu_perf_measure.py` on
`~/Desktop/space_exact/space_asbuilt_ride.igz`, at 2000×1400 physical pixels.
The machine was contended (the script records load and raw samples), so these
runs establish the frame-cost scale rather than a causal speedup.

| MSAA / AO / edges, profiles off | Before CPU / GPU ms | After CPU / GPU ms |
| --- | --- | --- |
| 4× / off / on | 7.571 / 25.601 | 6.190 / 23.959 |
| off / off / on | 6.884 / 22.503 | 5.930 / 19.720 |

The final paired run (`ride-axes-paired.json`) alternates axes off/on in eight
pairs per sample mode, reversing pair order, with three warm-up and ten measured
frames per block, paced at 80 ms. It uses one resident model and device.

| Final paired mode | Axes off CPU / GPU ms | Axes on CPU / GPU ms | CPU / GPU difference ms |
| --- | --- | --- | --- |
| 4× MSAA, AO off | 2.987 / 46.260 | 3.212 / 50.230 | +0.226 / +3.970 |
| Single sample, AO off | 6.151 / 34.415 | 5.128 / 36.276 | −1.023 / +1.861 |

**The ~0.3 ms end-to-end frame-cost gate is not established.** Default MSAA CPU
encoding increased by 0.216 ms (CPU total +0.226 ms), but GPU wall timestamps
varied substantially with contention, and the measured GPU deltas exceed the
requested allowance. Do not interpret the negative single-sample CPU delta as
an improvement. A quiet-machine GPU rerun is still needed before claiming the
full performance target.

Earlier line-list attempts are retained as `ride-axes-paired-contended.json`
and `ride-axes-lines-paired.json`: they showed ~0.95–1.76 ms CPU deltas and
inconsistent GPU deltas. The final implementation uses procedural triangles,
matching the renderer's edge-width method. It retains the visual result and
reduced the observed default CPU difference; the data do not establish an
isolated GPU cost. The standalone before/after JSONs above precede this final
line-to-quad optimization; final paired data and PNGs use the committed path.

## Reproduction

Use an external timeout (60 s for new documents; 240–290 s for ride runs).
The capture harness exits immediately after its screenshots and assertions.
The paired timing harness hides its native window after initialization.

```sh
INGETRAZO_WGPU=0 .venv-work/bin/python scripts/wgpu_billboards_axes_verify.py docs/benchmarks/billboards-axes gl --new-window
INGETRAZO_WGPU=1 .venv-work/bin/python scripts/wgpu_billboards_axes_verify.py docs/benchmarks/billboards-axes after --new-window
.venv-work/bin/python scripts/wgpu_axes_measure.py ~/Desktop/space_exact/space_asbuilt_ride.igz docs/benchmarks/billboards-axes/ride-axes-paired.json --new-window
```

Ride comparison uses `scripts/wgpu_look_compare.py MODEL --capture-only --output
OUTPUT` in an externally bounded standalone process (it does not invoke the
single-instance application entry point). PNGs are reduced with `sips -Z 1400`.
