# Edit context fade — 2026-11-09

Branch: `renderer/edit-context-fade`, based on `69701905`.

The native renderer now blends the rest of the model after texture sampling,
using GL's background-dependent fade colour and live fade preference. It
preserves opacity/depth behavior and reserves the override byte for view tints.
Hide mode rejects rest rows in the compute cull, including the pick pass;
Python also rejects stale hidden IDs before picking and snapping.

Membership follows the innermost open group's subtree, including billboards.
It is cached across frames, selection and fade-factor changes, and rebuilt on
context/mode changes or repacking/placement edits. `set_rest` performs a single
buffer write when flags change; the native flags survive highlight and row
updates. The added style row is RGB + fade at byte 128 (144 bytes total).

The edit box shares GL's oriented padded corners, screen hull, dash formula,
colour and physical pixel width. Per the requested overlay behavior, Metal's
box has no depth test; GL's scaffold does depth-test. This explains box edges
visible through faces on the Metal side. Empty clicks outside the box step out
one nested level; Shift/Ctrl/Cmd and existing selections retain GL semantics.

## Evidence

Every `*-comparison.png` is **GL left, Metal right**. The corresponding
`*-gl.png`, `*-wgpu.png` and JSON retain the individual captures and metadata.
All PNGs are resized with `sips -Z 1400` and are below 1 MB. Textures are enabled;
light/dark backgrounds are RGB .94/.08 with sky disabled. Captures use the same
fitted camera and the GL viewport's fade strength.

Nested paths (two edit levels):

- Pusher: `Groupe#32/Groupe#22`.
- Stairs: `Groupe#7/Groupe#75`.

- [pusher_car_rust, fade, light](pusher_car_rust-fade-light-comparison.png)
- [pusher_car_rust, fade, dark](pusher_car_rust-fade-dark-comparison.png)
- [pusher_car_rust, hide, light](pusher_car_rust-hide-light-comparison.png)
- [pusher_car_rust, hide, dark](pusher_car_rust-hide-dark-comparison.png)
- [space_asbuilt_stairs, fade, light](space_asbuilt_stairs-fade-light-comparison.png)
- [space_asbuilt_stairs, fade, dark](space_asbuilt_stairs-fade-dark-comparison.png)
- [space_asbuilt_stairs, hide, light](space_asbuilt_stairs-hide-light-comparison.png)
- [space_asbuilt_stairs, hide, dark](space_asbuilt_stairs-hide-dark-comparison.png)

- [Ride, fade, light](space_asbuilt_ride-fade-light-comparison.png)

Reproduce a pair with:

```sh
.venv-work/bin/python scripts/wgpu_look_compare.py MODEL --capture-only \
  --output docs/benchmarks/edit-context-fade --edit-group @nested \
  --edit-rest-mode fade --background light
```

Use an external 240-second process timeout (300 seconds for the ride).
`--edit-group` also accepts an exact name or slash-separated path. Capture-only
widgets use `WA_DontShowOnScreen`; no desktop capture or visible app launch was
used. Snap-index construction is disabled for capture-only runs.

## Validation

- Both Rust extensions built in release mode; no `target/debug` was created.
- Requested Python set (`tests/test_wgpu*.py`, `tests/test_nested_group_edit.py`)
  ran once: 199 passed, three failed initially. The failures were corrected
  (one renderer mock needed the new API; capture needed to tolerate a minimal
  viewport source). Only affected tests and new tests were rerun: 23 passed.
- Two further focused cases cover hidden inference/repacking and empty-click
  nesting; final `test_wgpu_edit_context.py`: 8 passed. All 204 distinct Python
  cases in the final requested set have passed, without rerunning the broad set.
- Targeted release Rust tests: `row_updates_preserve_selection_and_hover` and
  `section_and_fade_uniform_offsets`, both passed.
- The native shader pipelines successfully rendered all evidence pairs.
- No full suite, workflow edits, pushes, PRs or issues.

## Ride timing

Measurements use the same resident scene,
fixed camera and native offscreen render path. They exclude Python overlay
rasterization, scene packing, GL capture and surface presentation. Each mode
gets 45 frames, discards the first 10, and reports CPU/GPU/acquire medians from
`last_timings()`. GPU timestamps arrive asynchronously. Normal/fade is repeated
in the same session; this is not a before/after application benchmark.

The first ride attempt captured its pair but the benchmark summary failed
because `last_timings()` includes dictionaries after its first three fields.
The summary now extracts only the numeric fields, and the single ride evidence
case was retried with a 300-second process bound. No additional ride modes were
captured. Other development and the installed app were active on this Mac.

Result: **6.110 ms** for the initial flag write covering **76,008 rest rows**.
The subject path was `Groupe#310/Tie 93.1 | DS`. Mode-switch writes were
5.757, 4.951, 4.468 and 8.547 ms in chronological order. This measures the
Python-to-Rust call and queue write; membership discovery is outside that timer.

| Pass | Mode | CPU median ms | GPU median ms | Acquire/poll median ms |
| --- | --- | ---: | ---: | ---: |
| 1 | normal | 8.001 | 53.430 | 0.000042 |
| 2 | fade | 6.819 | 37.136 | 0.000041 |
| 3 | normal | 6.902 | 44.623 | 0.000041 |
| 4 | fade | 7.281 | 46.019 | 0.000041 |

`uptime`: `14:39 up 8 days, 8:28, 1 user, load averages: 16.38 16.68 15.60`.
There is no consistent fade slowdown across these samples. The substantial
GPU spread and concurrent work prevent a tight claim of unchanged frame cost.
No full-interaction wall-time equivalence is claimed: the box overlay adds
Python raster/upload work that this native A/B intentionally excludes.

Nothing from the requested image matrix is omitted. Exact frame-cost
invariance remains unproven under this machine load. The first failed timing
attempt and successful retry are disclosed above; only one ride image case is
retained. The installed app was not modified or interrupted.
