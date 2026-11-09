# P7 — Metal parity integration

Branch: `parity/p7-integration`. Base: `15455ee71eb4f59342e39830c2be380e3585dd14`.
Implementation commits: `4bf2fcad50d3168a1cedea91343164a5d099d507`
and `769ffd20f57340ccb9b331014687f46fd36def73`.
This report, measurements and captures are committed separately after those commits.
Local commits only: no push, PR, issue, comment, workflow edit, installed-app
launch, mapped capture window or corporate-network operation.

## Finding status

“Closed” refers to the named integration and tested scope, not whole-frame pixel
identity or physical-input certification. Twelve [paired crops](crops/manifest.json)
are OpenGL left / Metal right; each is ≤1400 px wide and <1 MB.

| Finding | State | Evidence and remaining boundary |
|---|---|---|
| G01 — loose selection/edge hover | Closed | [Visible selected slab face](crops/synthetic-selected-face.png), [edge hover](crops/synthetic-hover-edge.png); resident triangle stipple and depth-tested edge marks replace CPU dot sampling. Selection IDs resolve to cached prototype triangle ranges. |
| G20 — group selection | Closed | [Group](crops/synthetic-selected-group.png); native `group_selection_edges`, descendant rows, no face stipple. |
| G07/G08 — glass/tag opacity | Partial | [Glass/tag](crops/synthetic-guides-only.png); production effective-alpha ABI and OIT work, including backs. Weighted OIT still differs from GL’s ordered/dithered transparency (especially the annotated/selected fixture). Opacity propagation is closed; exact transparency look is not. |
| G10 — hidden geometry/objects | Closed | [Hidden](crops/synthetic-hidden.png); hidden face/edge streams and object rows use bit 4, exclude tag/navigator bit 5 and edit-hidden bit 7. Both document switches invalidate the pack. Placement/edit visibility refreshes ghosts; disabled switches do no ghost expansion/upload. Qt/facade tests cover tag exclusion and world-row updates. |
| G14 — soft edges | Closed | [Smooth cylinder](crops/smooth.png); source endpoint exclusions suppress internal profiles. Repeated source coordinates are welded for soft corner fans, also fixing the faceted exterior seen in P2. |
| G22 — previews/suppression | Partial | Push/Pull, Follow Me, Offset and face Move consume the shared native preview upload. Recessed Push/Pull Qt events verify index-buffer suppression without repacking, depth mesh upload, Escape clear/restore, and unchanged document attrs. Native raster tests cover depth/restoration. Transient meshes still have vertex materials only, no texture table; exhaustive tool/modifier/occlusion permutations are not certified. |
| G16 — export overlays | Partial | [Production `render_image(overlays=True)`](crops/synthetic-export-overlays.png) uses output-aspect P4 layout and excludes interactive feedback. P4 sheet/2× tests pass. Guide fallback has no depth attachment; export annotation occlusion is not supplied from a stale live ID buffer, so this is not full GL occlusion parity. |
| G17 — guides-only scheduling | Closed | [Guides-only](crops/synthetic-guides-only.png); annotations run independently of dimension/text presence. |
| G23 — inference glyphs/dashes | Partial | [Glyph gallery](crops/synthetic-glyphs.png) exercises the shared P4 marker/halo/dash helper now used by production. Axis badges are suppressed. Guide depth remains painter-only. Gallery is a controlled primitive comparison, not physical mouse-input evidence. |
| G24 — tool overlays/lock labels | Closed | Production calls `draw_tool_overlays` independently of document annotation presence; existing Walk/Flip/lock/linear-label tests pass. |
| G26 — directional rectangles | Closed | [Window](crops/synthetic-box-window.png), [crossing](crops/synthetic-box-crossing.png), [zoom](crops/synthetic-zoom-window.png). Harness sends Qt press/move events; no injected Metal rectangle. Tests caught and fixed QPointF→tuple conversion. |
| G03/G25 — reference inference | Closed | P6 prepare receives the scene; snap runs with no face row. Edge references and bounded nearby candidates use resident inference. Guide/axis pickers reuse projection-only GL helpers, never GL pick caches. Arc continuation calls the resident tangent API, with a test forbidding GL placement scans. Tests cover Tape references and actual Eraser guide click/undo. Hover cost below. |
| G12 — sun/shadows | Closed | [Shadows](crops/synthetic-shadows.png); shared date/time/georef/north direction, document toggle, technical-style/night/kill-switch policy and reference-ground receiver policy. P2’s reconstructed flat receiver normals and lack of translucent receiver shading remain native limitations. P5 reference geometry is not implemented here. |
| Unlisted default-front grey slab | Closed | [Guides-only](crops/synthetic-guides-only.png). A scene-wide layer-effect wrapper was being treated as explicit grey container paint even when its resolved paint was empty. It now retains alpha-zero unpainted provenance and the warm front-color path; unrelated-tag/front-tint regression tests pass. |
| Ride repeated-pack peak memory | Partial | Matching-back storage and unused UV-map copies are reduced, but the repeated-process RSS acceptance is not met; exact measurements and caveats below. |

The selected-face audit case now selects the visible slab top instead of its
obscured underside, so it actually demonstrates stipple/depth behavior. Raw
captures, successful argv/return codes and logs are in [runs.json](runs.json)
and `raw/`. All twelve final commands succeeded. Their only capture stderr is
the known first-frame GL sampler warning. P5’s missing magenta reference image
remains visible as a separate, pre-existing difference in these pairs.

## Opaque frame cost

[Final A/B](frame-ab-final.json): one resident ride, one process, paired opacity
ABI off/on per configuration; 10 warmups, 20 samples, 120 ms pacing, unshown
native host, `render(False)`. Earlier [full-base matrix](frame-base.json) and
[block-ordered A/B](frame-ab.json) are retained to expose machine variability.
The final paired run’s uptime was:

`16:10  up 8 days,  9:59, 2 users, load averages: 102.80 33.75 18.39`

This was a heavily contended shared Mac (load average over 100 at the recorded
point). Timings are observations, not a speedup or equal-time guarantee.
**All opaque OIT accumulation medians are zero; no opacity replay pass is added.**
Opaque off/on captures are byte-for-byte identical, SHA-256
`7ea37845baf146c7a27cfb00b70075ce460487f144fb240a54dc19ea289bba8c`. That proves identical opaque pixels, not identical elapsed milliseconds.

CPU / GPU medians, ms:

| Configuration | Alpha ABI off | Alpha ABI on |
|---|---:|---:|
| `msaa=False,ao=off,edges=True,profiles=False` | 6.75 / 22.54 | 7.44 / 20.08 |
| `msaa=False,ao=half,edges=True,profiles=False` | 6.80 / 22.11 | 8.35 / 21.81 |
| `msaa=False,ao=full,edges=True,profiles=False` | 7.84 / 18.23 | 4.38 / 21.86 |
| `msaa=True,ao=off,edges=True,profiles=False` | 6.38 / 28.48 | 8.22 / 27.23 |
| `msaa=True,ao=half,edges=True,profiles=False` | 7.34 / 30.44 | 9.00 / 22.34 |
| `msaa=True,ao=full,edges=True,profiles=False` | 7.05 / 19.70 | 8.04 / 24.56 |
| `msaa=False,ao=off,edges=False,profiles=False` | 3.66 / 11.02 | 6.74 / 9.91 |
| `msaa=False,ao=off,edges=True,profiles=True` | 7.52 / 28.60 | 8.36 / 31.14 |

## Hover cost

[Hover A/B](hover-ab.json) compares the base commit’s `hover` function against
the integrated function, compiled from Git, on the same packed ride/native
renderer/P6 index with Tape active. It samples 36 screen positions twice after
warmup; no OS cursor movement. Load/pack/index construction is outside timing.
This isolates integration cost; it is not a full historical installed-app A/B.

| | p50 ms | p95 ms |
|---|---:|---:|
| before | 1.38 | 6.48 |
| after | 7.83 | 13.58 |

The extra no-face candidate search is measurable. It remains bounded in this
sample (p95 <16 ms), with P6’s candidate caps and cached spatial structures;
this is not a guarantee for every model/camera. Uptime: `15:55  up 8 days,  9:44, 1 user, load averages: 8.42 10.18 10.61`.

## Pack time and memory

Two packs per process, retaining the previous result during the next pack.
[Before](pack-before.json) was measured before integration with the base core;
[after](pack-after.json) uses the final core. Both use the ride and the same
session, but the baseline overlapped initial setup/frame work and memory pressure
changed substantially. macOS peak RSS is process-resident high-water data, not
an allocator-live-byte measure. Do not interpret its difference as a controlled
leak measurement or claim the target has been achieved.

| Run | First / second pack seconds | First / repeated peak RSS, decimal GB |
|---|---:|---:|
| Before | 39.54 / 32.99 | 3.52 / 3.52 |
| After | 21.07 / 22.52 | 4.45 / 6.62 |

The output-byte investigation is conclusive: this ride contains **zero hidden
face/edge vertices** and a **four-byte texture atlas**, so neither retained
hidden faces nor atlas resolution explains P3’s growth. Its 887,876,696-byte
vertex stream is unchanged. Matching front/back colors were expanding to
**815,977,536 bytes of material corners**; the header-bit representation reduces
that to **255,552 bytes**, saving 815,721,984 bytes per retained pack (and matching
GPU storage). Core and render extensions must be rebuilt together.

Additional avoidable copies removed: the Rust bake borrows its read-only UV
mapping view, untextured packs use a broadcast zero mapping rather than a
face-sized allocation, per-prototype source copies are released before native
output allocation, and soft welding retains original position storage.
The intermediate borrowed-map measurement is retained in
[pack-intermediate-borrowed-maps.json](pack-intermediate-borrowed-maps.json).
Final first-pack peak is lower than that intermediate, but repeated peak remains
high. Source/concatenated topology, native prepared triangles, the old resident
pack, and allocator retention still overlap; no retained-hidden/atlas blame or
unproven leak fix is claimed. Further peak reduction needs a streamed/chunked
bake or explicit reusable build buffers, beyond the safe integration changes.

## Validation and reproduction

- [Permitted focused run](tests-focused.log): 453 passed, 11 skipped. The extra
  smooth/array-bake tests cover touched bake behavior; no full suite.
- [Integration/Arc regression run](tests-tangent.log): 63 passed, 2 native skips;
  the final focused run above also includes these tests, the Eraser guide
  click/undo and hidden-world refresh assertions.
- [Unshown Cocoa native run](tests-native.log): 26 passed, including opaque ABI
  pixel identity, scene-classification reset and compressed matching backs.
- [Render Rust release](cargo-render-release.log): 38 passed;
  [core Rust release](cargo-core-release.log): 6 passed.
- `git diff --check` clean; no remaining `TODO(P…)` in views/rust/scripts;
  no `target/debug`, workflow changes or remote writes.

Setup used `.venv-work`, local `.cargo-work`, Python 3.13, release-only maturin
for both crates; `VIRTUAL_ENV=$PWD/.venv-work` is required for the supplied venv
name. Render uses `--features extension-module` and
`CARGO_PROFILE_RELEASE_STRIP=none`.

All commands must remain externally bounded. Representative reproduction:

```sh
timeout 90 .venv-work/bin/python scripts/wgpu_look_compare.py docs/benchmarks/metal-parity/synthetic.igz --capture-only --live-frame --audit-case selected-face --output docs/benchmarks/metal-parity/wave1/p7/raw
timeout 30 env QT_QPA_PLATFORM=offscreen .venv-work/bin/python docs/benchmarks/metal-parity/wave1/p7/make-crops.py
timeout 400 .venv-work/bin/python docs/benchmarks/metal-parity/wave1/p7/perf-matrix.py MODEL OUTPUT
timeout 360 .venv-work/bin/python docs/benchmarks/metal-parity/wave1/p7/measure-hover.py MODEL OUTPUT 15455ee71eb4f59342e39830c2be380e3585dd14
timeout 300 env QT_QPA_PLATFORM=offscreen .venv-work/bin/python docs/benchmarks/metal-parity/wave1/p7/measure-pack.py MODEL OUTPUT
```

Physical focus/trackpad/HiDPI, real composer UI, exhaustive preview tool scenarios,
P5 imagery/geography, texture-bearing previews, exact OIT ordering, guide depth,
and a lower repeated-pack peak RSS remain outside the closed claims above.
