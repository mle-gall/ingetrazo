# Integration — R2b + AO (2026-11-09)

Base: `025a768e`. Local integration branch: `renderer/integrate-r2b-ao`.
No PR, issue, comment or push was created. Source models were read-only.

## Implementation

- R2b tool dispatch, Tape overlay, History-backed placement Move and resident
  diffs run on the compact renderer. GL viewport implementation is unchanged.
- Replacement geometry is expanded into 48-byte edge records and compacted
  into 28-byte face vertices. Indirect edge commands retain their hard-only
  counts; placement offsets occupy word 3 for edges and word 4 for faces.
- Allocation growth rebinds viewpoints, edge storage, profile, MSAA and X-ray
  resources. Logical prototype ranges exclude spare capacity from culling.
- Transform updates, visibility updates, tombstones and prototype edits dirty
  the cached ID target. The native smoke asserts cache validity before and
  after a matrix update and synchronous refresh.
- Sparse replacement material data preserves 32-byte corner records and
  remaps texture layers to their resident identities; new images append to
  the texture array. Resident memory reporting counts actual grown buffers.
- AO uses half resolution by default, respects style/Distance, and composites
  between faces and compact edges/overlays. MSAA keeps its color/depth between
  those passes. X-ray retains its weighted transparency path (AO disabled as
  on the source AO branch). AO-enabled frames currently refresh single-sample
  depth even with MSAA; this is a material performance cost.

## Reproduction

All commands below run in this worktree using `.venv-work`. Build logs are
adjacent. Each GUI subprocess is capped at 240 seconds. No debug outputs were
present in either crate target directory before captures.

```sh
python3.13 -m venv .venv-work
.venv-work/bin/pip install -r requirements.txt maturin
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work .venv-work/bin/maturin develop --release --manifest-path rust/ingetrazo_core/Cargo.toml
VIRTUAL_ENV=$PWD/.venv-work CARGO_HOME=$PWD/.cargo-work CARGO_PROFILE_RELEASE_STRIP=none .venv-work/bin/maturin develop --release --features extension-module --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest -q tests/test_wgpu_*
CARGO_HOME=$PWD/.cargo-work cargo test --release --manifest-path rust/ingetrazo_render/Cargo.toml
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow' --batches 24
```

GPU timings are asynchronous timestamp medians, not presentation latency.
The full suite runs concurrently with diagnostics; other machine workloads
are uncontrolled. Compare these samples with that limitation in mind.
The first track GL comparison exceeded its 240-second cap; its log is retained.
The initial ride update attempt exposed a stale diagnostic viewport stub;
the corrected run is `ride-updates.txt`.

## Remaining scope

R3: live mesh tools, loose-face transforms and sheets. Append-only replacement
ranges still need reclamation for sustained mesh editing. Native window tool
activation is already integrated (`26b58367`); the source R2b report's guard
checkpoint is historical. Hard-edge GPU cost and cold picking remain open
performance items; integration does not claim to close their prior 30 ms and
79 ms baselines. MSAA plus AO also needs depth-pass cost reduction.

## Memory, picking and parity

| Ride metric | Integrated result |
| --- | ---: |
| Resident buffers, including spare allocation capacity | 1,169,587,060 bytes (1.170 GB) |
| Settled pick | 1.31 ms |
| Cold pick after a camera change | 90.90 ms |
| Faces + hard edges, profiles off, MSAA off | 31.39 ms GPU |
| Faces + profiles, MSAA off | 46.77 ms GPU |

[Raw memory/picking run](space_asbuilt_ride-metal-only.json).
[AO off/half/full GPU timing table](ao-costs.md) includes both MSAA modes on
marquee, pusher car, track and the full ride. Raw JSON files also contain CPU
and wall medians.

Pixel comparisons against the committed compact-edge captures are **exact**:
marquee, pusher car and marquee X-ray each have RGB MAE 0 and zero changed
pixels at 2000×1400. See [parity.json](parity.json). This checks profiles,
textures, red wheels and weighted X-ray with AO off independently of the new
AO look. The comparisons below put GL on the left and Metal on the right.

- [Marquee AO comparison](marquee-ao-half-comparison.png)
- [Pusher car AO comparison](pusher_car_rust-ao-half-comparison.png)
- [Ride section AO comparison](space_asbuilt_ride-section-ao-half-comparison.png)
- [Marquee profiles/textures](marquee-comparison.png)
- [Pusher car red wheels](pusher_car_rust-comparison.png)
- [Marquee X-ray](marquee-xray-comparison.png)

AO half/full remains substantially more expensive with MSAA because the
current integration renders single-sample geometry for AO depth as well as
multisample color. Timing boundaries include that work. This is not a claim
that the 60 Hz ride budget has been met.

## Update diagnostic configuration

The first successful update diagnostic inherited the renderer's current MSAA-on
default: move through pick 72.99 ms and dispatched drag p95 60.07 ms. It is
retained in `ride-updates-msaa.json`. The R2b source benchmark used MSAA off;
the final script now explicitly disables MSAA and AO for that comparison,
rather than relying on constructor defaults. Profiles remain at the scene
style setting. Tagging submitted zero calls; shared insertion submitted one
row in the MSAA run as well.

The final MSAA-off/AO-off [update table](updates.md) records move-through-pick
47.10 ms (passes 50 ms), tagging zero renderer calls and insertion one row.
Dispatched drag p95 is **38.36 ms**, so the 33 ms gate remains unmet. Full
per-frame measurements are in [ride-updates.json](ride-updates.json).

Focused validation: **73 Python tests passed**, **21 renderer Rust tests
passed**. The final native smoke completed and explicitly verified cached-ID
invalidation after an instance update. See `focused.txt`, `rust-tests.txt`
and `smoke.txt`.

## Integration commits

- `02191554`: integrate R2b tools and compact resident update bindings.
- `a86f9518`: composite AO before compact edges in single/MSAA rendering.
- `b3ea0060`: replacement materials, native cached-ID regression and grown-buffer accounting.
- `67b73a6a`: resident texture identities and complete material corner records.
- `335a3e79`: diagnostic viewport uses the current style interface; AO off for updates.
- `ea2c88c4`: explicit original single-sample update comparison configuration.

Builds use the requested isolated Cargo cache and interpreter. Renderer builds
emit one existing unused `multisampled` helper warning. Native smoke runs on
the actual Metal surface; Python tests use `QT_QPA_PLATFORM=offscreen`.

## Full-suite result

The single bounded `scripts/pytest_batches.py -m 'not slow' --batches 24` run
completed all batches in **1,312 seconds**: **7,187 passed, 18 failed,
142 skipped, 2 xfailed, 805 deselected** (60 reported warnings). No batch
exceeded 30 minutes and none required splitting or restarting. Exit status 1
reflects the expected failures, not a crash or timeout. [Full log](suite.txt).

Against the supplied 19-failure baseline: **zero new failures**. The reproduced
failures are all 14 translation catalogs (including Arabic), cached cursor
pick, extension-author/license wrapping, hidden-panel document retention and
extension-toolbar bold names. The baseline swatch-tooltip failure did not
reproduce. Final focused tests cover the integrated renderer/update/material
code separately; benchmark-interface fixes only change diagnostic scripts.
