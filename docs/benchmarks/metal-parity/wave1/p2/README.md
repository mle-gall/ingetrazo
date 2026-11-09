# P2 native raster implementation

Branch: `parity/p2-raster`, based on `6b80e856`. Local commit only; no push,
PR, issue, comment, workflow edit, installed-app launch or mapped window.

## Findings and handoff

| Finding | Result and acceptance boundary |
|---|---|
| G07/G08 | Native effective-alpha OIT implemented and pixel-tested with direct alpha bytes 64/255. Glass/tag crop uses explicitly synthetic pending-P3 alpha data. Production enablement waits for P3's bake. |
| G18 | Regular texture partial alpha blends; face-me keeps the hard 0.5 cut. Both sampling modes have pixel tests, plus the alpha-band crop. GL's existing below-0.5 dithering is intentionally not copied for regular image alpha. |
| G12 | Cached sun map, sun illumination, cast shadows and ground receiver implemented; shadow crop and native toggle tests pass. Flat depth-derived receiver normals remain a limitation on smooth surfaces. |
| G14 | Explicit soft endpoint handoff converts hard lines to silhouette candidates and excludes them from profiles-off commands. The smooth crop has no internal seams. Production metadata comes from P3; the fixture's corner shading remains faceted in Metal and is not claimed fixed here. |
| G20 | Python style enables group edge highlights without face dots. A separate loose-face stipple API is pixel-tested. P1 supplies loose-face triangles and any group enclosure edges. |
| G22 | Depth-tested transient triangles/edges and real index-buffer suppression/restoration are implemented and pixel-tested at 1×/4×. P1 wires tool lifetimes; P3/P1 resolve face IDs to triangle ranges. |
| G27 | GL constants remain 0.6 face opacity / 0.6 hidden-edge fade; unpainted backs retain front paint in X-ray. Color is improved, but weighted overlap remains visibly different from GL's ordered blending. **Not fully closed.** |
| G28 | AO's bounce formula now consumes display colors like GL and converts the resulting multiplier back to linear. OIT does not write AO depth. Opaque contact evidence is recaptured; pixel identity is not claimed. |
| G29 | Face-slope fill bias plus caps on segments longer than 4px gives continuous pusher rim coverage in the final crop. Extending subpixel segments was rejected after a measured MSAA regression. |
| G30 | Strict depth plus a small away bias prevents the blue axis crossing the face-me figure. Final crop confirms it. |
| G10 support | Hidden face/edge range API, object-row reveal, stipple/grid passes and opt-in controls provided; native hidden-face toggle tested. P3/P1 must supply ranges and refresh transformed ghosts. |

The native portions of G07/G08/G14/G20/G22 are ready for integration, not
end-to-end application closures before the parent wires their data/call sites.
No edits were made to P1/P3/P4/P6 files or P5 reference modules.

## API / TODO contract

See the detailed [renderer API](../../../../../rust/ingetrazo_render/README.md#p2-raster-parity-api-wave-1).
New methods: `set_preview_mesh`, `set_face_marks`, `set_suppressed_faces`,
`set_profile_exclusions`, `set_hidden_geometry` (empty/inactive initially).
Style additions: `material_opacity=False`, `group_selection_edges=False`
(native; Python payload enables it), `show_hidden_geometry=False`,
`show_hidden_objects=False`, `shadows=False`, `sun_direction=(0,0,1)`,
`shadow_darkness=.55`, `ground_shadows=True`, `shadow_matrix=identity`.
No public vertex/instance/command layout or flag bit was changed. The style
uniform grows to 160 bytes while section/fade remain at bytes 112/128.

`TODO(P1)` / `TODO(P1/P3)` markers cover preview/selection lifetimes, face range
resolution, hidden object IDs and refresh, and reference-ground shadow policy.
`TODO(P3)` markers cover alpha enablement, hidden ranges and soft metadata.
Suppression affects all placements of a shared prototype; duplicate it for a
placement-local edit. Transient previews and ghosts currently use vertex
materials, not texture tables. The sun receiver does not shade translucent
faces. X-ray exact ordering and smooth-normal sun receivers remain out of this
implementation. No P5 reference pass registration was possible without that
package's new modules in this worktree.

## Verification

- [Native raster](pytest-native.log): **12 passed**, unshown Cocoa NSView,
  including material/texture alpha at both sample counts, billboard threshold,
  opaque occlusion, suppression restoration, previews, face marks and toggles.
- [Focused Python](pytest-focused.log): **183 passed, 9 skipped**, only the new
  file plus `tests/test_wgpu*.py`, run once. Skips are native NSView checks under
  Qt offscreen; those passed in the separate native run. Existing Qt mirrored()
  deprecation warnings only.
- [Rust release](cargo-test-release.log): **38 passed**. Metal pipeline creation
  covers 1×/4× preview/marks/ghosts/sun, plus existing MSAA/OIT/AO tests. Existing
  unused `multisampled` warning only. No `target/debug` directories exist.
- All captures use the established `--capture-only --live-frame --audit-case`
  harness on unshown hosts. The new test file wraps it to inject synthetic P3
  data; no production pack/view edits. The first-frame GL sampler warning is
  the pre-existing audit warning; warmed reference captures are populated.
- [Crops](crops/manifest.json): identical rectangles, GL left / Metal right,
  maximum width 1380px. `make-crops.py` reproduces them. The pusher crop is
  deliberately tight around the MSAA rim. Raw paired PNGs and JSON remain here.

Example (externally bound with `subprocess.run(..., timeout=90)`):

```sh
PYTHONPATH=. .venv-work/bin/python tests/test_metal_parity_raster.py   docs/benchmarks/metal-parity/synthetic.igz --capture-only --live-frame   --audit-case guides-only --output docs/benchmarks/metal-parity/wave1/p2
```

## Same-session ride performance

`perf-matrix.py` preserves the original `scripts/wgpu_perf_measure.py` matrix,
10 warmups, 20 samples and 120ms pacing, replacing window mapping/presentation
with the audit's unshown native host. The archived baseline extension was
loaded with `P2_BASELINE=1`; candidate uses the isolated release install.
Every run had a 290-second external timeout. `perf-shadow-cost.py` adds same
resident-scene off/on/off/on shadow samples at 1×/4×. No GUI was presented.

The initial `perf-before.json` / `perf-after.json` pair records an intermediate
regression (unconditional caps inflated tiny edges). It is **not** acceptance
for the final code. `perf-ab-baseline.json` / `perf-ab-candidate.json` verify the
cap correction back-to-back. `perf-final.json` repeats the entire matrix after
adding the face-slope fill bias and records final shadow cost.

Baseline uptime: `15:22  up 8 days,  9:12, 1 user, load averages: 7.51 9.53 13.16`

Final uptime: `15:25  up 8 days,  9:15, 1 user, load averages: 8.76 8.92 12.18`

Medians in ms, **CPU / GPU**. All new optional passes off; AO/MSAA vary as in
the original matrix. These loaded-Mac samples do not establish a speedup.

| Frame configuration | Baseline | Final |
|---|---:|---:|
| `msaa=False,ao=off,edges=True,profiles=False` | 6.54 / 22.16 | 7.48 / 17.88 |
| `msaa=False,ao=half,edges=True,profiles=False` | 7.47 / 15.01 | 7.43 / 21.55 |
| `msaa=False,ao=full,edges=True,profiles=False` | 8.10 / 16.26 | 7.05 / 19.80 |
| `msaa=True,ao=off,edges=True,profiles=False` | 6.67 / 27.78 | 8.94 / 19.00 |
| `msaa=True,ao=half,edges=True,profiles=False` | 6.86 / 27.19 | 8.63 / 26.21 |
| `msaa=True,ao=full,edges=True,profiles=False` | 7.83 / 23.40 | 7.37 / 28.09 |
| `msaa=False,ao=off,edges=False,profiles=False` | 4.15 / 11.65 | 4.60 / 11.49 |
| `msaa=False,ao=off,edges=True,profiles=True` | 7.02 / 28.08 | 7.09 / 24.64 |

The final GPU ratios span roughly 0.68–1.44×, below the stated 2–3× machine
noise; there is no consistent feature-off regression. Single-sample no-AO
edges: 22.16→17.88ms GPU; MSAA no-AO: 27.78→19.00ms GPU. CPU single-sample
no-AO edges is 6.54→7.48ms. Raw samples and load averages are retained so these
are not presented as isolated-machine performance claims.

Final shadow off/on/off/on GPU medians:

| Samples | Off → on (first pair) | Off → on (second pair) |
|---|---:|---:|
| 1× | 17.77 → 18.27ms | 26.33 → 24.13ms |
| 4× | 21.35 → 23.38ms | 30.14 → 22.49ms |

First-pair warm cost is +0.50ms (1×), +2.03ms (4×); second-pair load drift
exceeds the effect. Cold enable CPU encode/submit is 11.9–13.6ms; the GPU map
build is asynchronous and not separately timestamped, so this is **not** its
GPU cost. Disabled shadows encode no shadow pass, though the map allocation
is 16MiB per renderer. `gpu_memory` in legacy capture JSON is resident geometry
accounting, not total renderer/attachment memory.
