# P4 overlay helper acceptance

Branch: `parity/p4-overlay`, based on `6b80e856`. Local commit only.

## Result

251 tests passed (71 new P4 cases plus tests/test_wgpu*.py), 35 existing
QImage.mirrored deprecation warnings. The focused existing tests ran once.
Both crates built in release, renderer with extension-module and
CARGO_PROFILE_RELEASE_STRIP=none. No Rust changes or target/debug directories.

All six capture commands in runs.json completed with exit 0. No widget was
shown: the harness uses QOffscreenSurface for GL and an unshown Metal host.
The only capture warning was the known first-frame GL sampler warning.
The compact PNG pairs are GL left / Metal right, 1400 pixels wide:
glyphs, box-window, box-crossing, zoom-window, guides-only, export-overlays.
Full source pairs, individual images, timing JSON and stderr logs are retained.

The opt-in --p4-overlays audit hook integrates these helpers only within
scripts/wgpu_look_compare.py. P1 production scheduling files remain untouched.
Its export case composites annotations on native readback; sheet sizes and
2x scaling are independently tested on QImages. The glyph gallery deliberately
uses one green input color in both renderers to isolate shape/halo/dash parity.

## Integration contract

See views/wgpu_annotations.py's module docstring for lifecycle, coordinate and
occlusion requirements.

- draw_snap_indicator(painter, snap, project, clip_line, labels=True): complete
  SnapResult marker, contextual color, translated label and inference guides.
- snap_glyph(point, kind, color): backward-compatible single marker primitive;
  color is a QColor or Qt color string. Full SnapResult path is preferred.
- selection_rectangle(start, end, zoom=False): append after P1's drag threshold;
  endpoints must retain drag direction.
- draw_annotations(painter, scene, camera, logical_size,
  annotations_only=False, occluded=None, hover=None): live document annotations,
  also when guides/section widgets are the only overlay content; returns layout.
- draw_tool_overlays(painter, tools, labels=True): independent live tool hook
  and prioritized reference/axis/plane/inference/linear-mode labels.
- composite_annotations(image, scene, camera, logical_size=...,
  overlays=True, annotations_only=False, occluded=None): copied capture with
  output-aspect projection and uniform scaling; no interactive tool feedback.
- guide_segments(scene, camera): world-space dash segments and selected flags,
  reusable by a future depth-tested native pass.
- draw_guide_lines(painter, layout): painter fallback for those world dashes.

AnnotationLayout isolates projection from live widget dimensions; its camera
copy is set to the target aspect. Width sets uniform annotation scale, and the
virtual logical height follows the output aspect. This avoids stretching text
and arrows for portrait sheets while preserving the existing same-aspect export.
Export occlusion callbacks must be valid for the capture camera. Omitting one
makes dimensions/leaders visible; a stale live pick buffer is never used.

## Limits and remaining integration

QImage has no depth buffer. Document guide dash spacing/reach/colors match the
GL world geometry, but guides can show through faces. This is explicit, not a
claim of depth parity. Dimensions/leaders accept a CPU visibility callback.
Guide raster AA can differ from GL line rasterization.

P1 must integrate scheduling, capture composition and box helper calls; the
audit hook is not production wiring. Existing image-plane, transparency,
locked-layer and other packages' differences remain visible in scene pairs.

The reference Flip tool paints translucent axis planes, not arrows; the helper
calls that exact tool hook. Walk crosshair and Flip are tested with no dimension
or text annotations. Lock labels use the shared GL painter/localization rules.
No installed app, interactive screen takeover, push, PR, issue, workflow edits,
full suite or corporate-network operation occurred.
