# R-look 3c — 2026-11-09

GL is left, Metal is right in every comparison. The GL viewport implementation and its defaults were not changed.

## Cost table

All captures are 2000×1400 (2×), medians after warmup. CPU is elapsed time inside `Renderer.render`, including drawable waits; wall adds Python frame preparation. GPU timestamps are asynchronous and can lag the submitted frame. Stage medians are independent and need not sum to the median total. Tests/builds were also running on the shared machine, so differences are not controlled speedup claims.

The paired baseline uses renderer commit `22f57426` with only the same stage timers and offscreen diagnostic added, loaded from a separate worktree-local wheel. Both versions use the current Python capture harness. The original historical R-look 2 measurements remain in [samples.md](../r-look-2/samples.md).

| Model / renderer | MSAA | Edges | CPU ms | GPU ms | Wall ms | Acquire ms | Encode ms | Submit ms |
|---|---|---|---:|---:|---:|---:|---:|---:|
| marquee, 22f control | False | False | 14.08 | 0.55 | 14.28 | 13.63 | 0.31 | 0.12 |
| marquee, 3c | False | False | 8.36 | 0.37 | 8.55 | 7.99 | 0.28 | 0.10 |
| marquee, 22f control | False | True | 14.11 | 0.79 | 14.31 | 13.68 | 0.30 | 0.12 |
| marquee, 3c | False | True | 8.38 | 0.72 | 8.57 | 7.98 | 0.28 | 0.10 |
| marquee, 22f control | True | False | 12.20 | 0.84 | 12.36 | 11.63 | 0.39 | 0.13 |
| marquee, 3c | True | False | 8.45 | 0.57 | 8.63 | 7.99 | 0.38 | 0.11 |
| marquee, 22f control | True | True | 13.13 | 1.05 | 13.34 | 12.54 | 0.42 | 0.14 |
| marquee, 3c | True | True | 8.36 | 1.25 | 8.55 | 7.88 | 0.37 | 0.10 |
| pusher_car_rust, 22f control | False | False | 12.55 | 1.34 | 12.76 | 12.13 | 0.28 | 0.11 |
| pusher_car_rust, 3c | False | False | 11.66 | 1.52 | 11.85 | 11.23 | 0.29 | 0.11 |
| pusher_car_rust, 22f control | False | True | 13.39 | 1.58 | 13.55 | 12.86 | 0.30 | 0.11 |
| pusher_car_rust, 3c | False | True | 13.28 | 2.78 | 13.51 | 12.82 | 0.32 | 0.12 |
| pusher_car_rust, 22f control | True | False | 13.14 | 2.34 | 13.38 | 12.55 | 0.42 | 0.14 |
| pusher_car_rust, 3c | True | False | 13.10 | 2.39 | 13.32 | 12.52 | 0.43 | 0.13 |
| pusher_car_rust, 22f control | True | True | 14.41 | 2.94 | 14.62 | 13.75 | 0.46 | 0.15 |
| pusher_car_rust, 3c | True | True | 17.72 | 5.98 | 18.03 | 16.86 | 0.62 | 0.18 |
| space_asbuilt_ride, 22f control | False | False | 7.88 | 8.22 | 8.15 | 5.76 | 1.92 | 0.15 |
| space_asbuilt_ride, 3c | False | False | 7.75 | 9.48 | 8.03 | 5.74 | 1.85 | 0.13 |
| space_asbuilt_ride, 22f control | False | True | 8.33 | 14.32 | 8.73 | 2.36 | 6.36 | 0.17 |
| space_asbuilt_ride, 3c | False | True | 26.90 | 26.21 | 27.21 | 19.40 | 11.96 | 0.17 |
| space_asbuilt_ride, 22f control | True | False | 22.42 | 24.47 | 23.06 | 0.04 | 18.30 | 0.22 |
| space_asbuilt_ride, 3c | True | False | 56.30 | 54.13 | 56.64 | 49.23 | 3.00 | 0.13 |
| space_asbuilt_ride, 22f control | True | True | 59.28 | 60.34 | 59.47 | 52.78 | 6.09 | 0.14 |
| space_asbuilt_ride, 3c | True | True | 84.46 | 83.95 | 84.67 | 77.94 | 6.59 | 0.15 |

| Same passes offscreen, MSAA and edges on | Before CPU/GPU/wall ms | After CPU/GPU/wall ms |
|---|---:|---:|
| marquee | 0.90/0.52/0.91 | 0.80/0.99/0.80 |
| pusher_car_rust | 1.68/4.11/1.68 | 2.54/8.43/2.55 |
| space_asbuilt_ride | 11.89/46.36/11.91 | 13.56/110.68/13.57 |
| One triangle | 2.88/3.30/2.88 | 0.40/0.28/0.40 |

| Pusher X-ray (3c) | CPU ms | GPU ms | Wall ms |
|---|---:|---:|---:|
| msaa=False,edges=False | 8.42 | 1.89 | 8.61 |
| msaa=False,edges=True | 7.98 | 8.42 | 8.18 |
| msaa=True,edges=False | 8.46 | 1.90 | 8.67 |
| msaa=True,edges=True | 7.79 | 9.39 | 8.08 |

X-ray rows labelled MSAA=True request MSAA but currently use the single-sample OIT path. Raw JSON files include polling/presentation stages and the X-ray offscreen control. `before-edge-shortcut/` preserves the intermediate measurements before skipping unnecessary hard-edge classification; those are not the final results.

## CPU-floor diagnosis

The apparent 12–14 ms floor is predominantly `get_current_texture()` / Metal drawable acquisition. The final one-triangle control spends 9.31 ms acquiring a drawable, 0.31 ms encoding, 0.08 ms submitting and 0.003 ms polling. The same passes offscreen take 0.40 ms total CPU. The baseline control is also low-single-digit offscreen: this is a diagnosis of a misleading CPU-floor interpretation, not a newly eliminated 13 ms of computation.

`AutoNoVsync` was already enabled. Drawable/compositor pacing and GPU backpressure remain in on-screen timings; no wait is silently subtracted from the public result. On the ride, real GPU and encoding costs remain high, as the table shows.

The frame loop now calculates each camera matrix once after updating aspect and only sends changed style payloads across PyO3. `render(False)` reuses a same-size resident target and executes the same passes without acquisition/presentation. It is a diagnostic, not an acceleration of on-screen presentation. Hard-edge silhouette arithmetic is skipped when it cannot affect width; soft candidates are still classified each frame.

The ride initially failed to open with macOS `Need authenticator`; a later retry succeeded, and both final/control runs completed inside their 240-second subprocess bounds.

## Rendering and remaining differences

- Edge uploads still enter through `edges::expand`. A resident 52-byte vertex carries two adjacent triangle normals; the external scene upload remains 28 bytes. Projected face-side classification happens every frame on the GPU, including mirrored placements. Missing non-coplanar triangle edges become profile candidates and collapse unless silhouettes. This increases resident geometry and GPU cost; the table includes that cost.
- Profile width defaults to GL’s existing one-physical-pixel profile behavior; an optional style `profile_width` is passed through. Profile color is the existing edge color, as in GL. Back-edge dashes use four logical pixels, scaled by DPR.
- X-ray uses GL’s 0.6 face opacity, weighted blended order-independent accumulation with constant weights, a depth-only face pass, 60% background wash for hidden edges, and soft profiles on top. Weighted blending is approximate and linear-space blending differs from GL’s display-referred blending.
- X-ray and back-edge styles currently bypass the old color-only MSAA replay, which would overwrite their results. These styles are single-sample; normal styles retain MSAA.
- The upload contains triangle geometry and visible hard edges, but no explicit soft/hidden-edge metadata. Reconstructed candidates can include intentionally hidden non-coplanar seams. Exact authored-hidden-edge parity needs metadata from the scene bake; this implementation does not change the other agent’s scene/material columns.
- Pusher X-ray still differs visibly from GL due to the missing texture/back-material work, different compositing, and aliasing. It is not a claim of complete GL visual parity. No texture or AO implementation was added here.

## Images

- [Marquee, profiles on](marquee-comparison.png)
- [Marquee, profiles off](marquee-profiles-off-comparison.png)
- [Marquee, back edges](marquee-back-edges-comparison.png)
- [Pusher car, normal](pusher_car_rust-comparison.png)
- [Pusher car, X-ray](pusher_car_rust-xray-comparison.png)
- [Ride](space_asbuilt_ride-comparison.png)

Baseline captures and JSONs are under [baseline/](baseline/).

## Validation

Both crates built using the private `.venv-work` interpreter and `CARGO_HOME=$PWD/.cargo-work`. Render builds used `--features extension-module` and `CARGO_PROFILE_RELEASE_STRIP=none`. No new dependency was added.

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work PATH=$PWD/.venv-work/bin:$PATH CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work PATH=$PWD/.venv-work/bin:$PATH CARGO_HOME=$PWD/.cargo-work CARGO_PROFILE_RELEASE_STRIP=none .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_render/Cargo.toml --features extension-module
CARGO_INCREMENTAL=0 CARGO_HOME=$PWD/.cargo-work PYO3_PYTHON=$PWD/.venv-work/bin/python cargo test --manifest-path rust/ingetrazo_render/Cargo.toml --lib
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_style.py tests/test_wgpu_scene.py tests/test_wgpu_interaction.py
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m "not slow" --batches 32
```

Rust: 9 passed, including silhouette classification, suppression of coplanar triangulation diagonals, edge expansion, X-ray blend math and Metal pipeline validation. Focused Python: 39 passed. All GUI capture subprocesses were bounded to 240 seconds; the tiny control to 120 seconds.

The single full run used 32 batches and finished in 1,908 seconds: **7,079 passed, 20 failed, 142 skipped, 2 xfailed, 128 errors, 805 deselected**. No batch exceeded 30 minutes or required splitting.

Two failures and all 128 setup/teardown errors came from the transient full disk in `test_outliner.py` and `test_plugin_loader.py`. A targeted retry of those two files passed **115/115** after space became available. The remaining **18 failures match the supplied baseline**: 14 translations (including Arabic), cursor pick, extension preview wrapping, hidden-panel lifetime, and toolbar bold. The supplied baseline swatch-tooltip failure did not reproduce. This is an environment-contaminated full run plus a clean targeted retry, not a claim of a clean all-pass suite.

Logs: [full suite](validation-full-suite.log), [disk retry](validation-disk-retry.log), [focused Python](validation-focused.log), [Rust](validation-rust.log).

Capture commands (each invoked in a subprocess with a 240-second timeout):

```sh
.venv-work/bin/python scripts/wgpu_look_compare.py ~/code/ingetrazo-bench/marquee.igz --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3c
# Also --profiles-off --capture-only and --back-edges --capture-only.
.venv-work/bin/python scripts/wgpu_look_compare.py ~/code/ingetrazo-bench/pusher_car_rust.igz --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3c
# Also --mode xray.
.venv-work/bin/python scripts/wgpu_look_compare.py /Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz --output docs/benchmarks/wgpu-look-2026-11-09/r-look-3c
.venv-work/bin/python scripts/wgpu_frame_floor.py
```

The tiny control used a 120-second external timeout. No PR, push, issue, or remote comment was created.
