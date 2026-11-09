# R-look 2 — 2026-11-09 — partial implementation

This branch does **not** meet look-parity acceptance. It implements hard-edge
quads, the unpainted placement sentinel, and instance highlight dots. It does
not implement AO, profiles, back edges, UVs/atlas, distinct back materials or
sorted/order-independent X-ray. No GL code or defaults changed.

## What now holds

- Hard-edge commands expand to six vertices per segment at upload in
  `edges.rs`; `edges.wgsl` expands them in physical screen pixels, clips a
  crossing endpoint against the near plane before perspective division, and
  retains the existing constant -2 / slope -1 depth bias. Single-sample ID
  and 4× MSAA color paths both draw these triangles. No scene-bake ABI change.
- An optional `edge_width` style payload entry accepts finite widths 0–64
  physical pixels, default 1. The current GL `Style` has no width property;
  this is a native renderer control, not a new preferences control.
- Instance paint alpha zero means unpainted. An explicit gray still has
  alpha 255. Style-generated Front tint stays unpainted, allowing shader
  updates without rebaking. Default fronts use `(0.96, 0.95, 0.925)` times
  Front tint; painted faces retain their material color.
- Selected/hovered instances use 2×2 dots every six physical pixels, orange
  or contrasting blue using GL's hue/saturation/value thresholds. Edge
  highlights use selection orange and hover blue. The existing highlight
  API is instance-granular: this does not add per-face picking/highlighting
  or group-box overlays. Those distinctions remain visible differences.

## Cost and limitations

The upload expansion keeps the input vertices and indices, appending six
28-byte vertices and six u32 indices per edge: **192 extra resident bytes per
hard edge**, plus temporary CPU copies during upload. Expansion happens once
per scene replacement. This is a deliberately isolated implementation; future
incremental scene updates must run the same expansion on replaced edge data.
There is no adjacency classification or silhouette unit test because neither
is implemented. The edge unit test covers endpoint expansion and preservation
of face commands; the Metal test validates the actual shader pipelines.

Timings below are whole-frame medians, with asynchronous GPU timing, following
the original comparison script's 10 warm-up / 35 sample procedure. They are
not isolated pass costs, and CPU subtraction is not a valid pass estimate.
Other worktrees were running tests concurrently. No performance acceptance
claim is made. Every GUI subprocess has an external 240-second timeout.

## Captures

Each comparison has GL left and Metal right, the same camera, 1000×700 logical
/ 2000×1400 physical pixels. The default and edges-off pairs compare the warm
front tint and hard edges. The `width4.0` pairs are width diagnostics: the GL
side retains its normal width. They are not width-parity evidence. GL export
still draws axes absent in Metal. The ride uses full bounds, not a curated
ride-section camera. Texture detail remains absent in Metal, especially on
the pusher wheels and marquee stone bases. Profiles and X-ray differences
from the original report remain unresolved.

Reproduce after the two release builds from the parent report:

```sh
.venv-work/bin/python scripts/wgpu_look_compare.py MODEL --output docs/benchmarks/wgpu-look-2026-11-09/r-look-2
.venv-work/bin/python scripts/wgpu_look_compare.py MODEL --output docs/benchmarks/wgpu-look-2026-11-09/r-look-2 --edges-off --capture-only
.venv-work/bin/python scripts/wgpu_look_compare.py MODEL --output docs/benchmarks/wgpu-look-2026-11-09/r-look-2 --edge-width 4 --capture-only
```

The script also accepts `--highlight selected|hovered`, but GL export omits
selection overlays, so that diagnostic is not comparative selection evidence.

## Validation

Both mandated release builds succeeded (render with `--features extension-module`
and `CARGO_PROFILE_RELEASE_STRIP=none`). Cargo home and Python environment are
worktree-local. No new dependencies were added.

- Core Rust: 5 passed (`PYO3_PYTHON=$PWD/.venv-work/bin/python CARGO_HOME=$PWD/.cargo-work cargo test --manifest-path rust/ingetrazo_core/Cargo.toml`).
- Renderer Rust: 6 passed (same command with `ingetrazo_render`).
- Python: 24 passed (`QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_scene.py tests/test_wgpu_style.py`).
- An earlier Python run skipped native tests before the core install completed;
  those skips are not counted as validation.
- No UV/back-material handoff tests are claimed: those columns are absent.


## Capture outcome and bounded-suite result

Eight comparison images were produced: pusher and marquee default, edges
off and width 4; ride edges off and width 4. Seven processes exited normally.
Ride default timed out without an image; ride edges-off wrote its images and
JSON before timing out during shutdown. Both were terminated at the external
240-second bound. No current ride timing sample was obtained. The ride width diagnostic completed and was visually inspected; it
is intentionally much heavier than the GL reference. There is no curated
ride-section capture or per-item three-model acceptance set.

The suite was invoked once through `scripts/pytest_batches.py -m 'not slow'
with `--batches 24`, a 1,800-second per-batch timeout and a 720-second overall
bound. Four completed batches report **1,267 passed, 18 failed, 48 skipped,
1 deselected**. All 18 failures match the supplied baseline: 14 translations,
hidden-panel retention, toolbar bold, cached cursor pick and extension wrap.
The baseline swatch-tooltip case has not been verified. The incomplete batch
is excluded from counts. No batch reached 30 minutes, so no post-timeout file
split was triggered. **Full-suite regression status remains unverified.**

See [samples and image inventory](samples.md) and [validation summary](validation.json).
