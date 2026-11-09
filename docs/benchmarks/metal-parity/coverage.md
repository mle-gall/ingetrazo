# Coverage ledger

V = paired pixels; P = executable probe/test; S = code inspected; U = untested acceptance. A “same” result is restricted to the named state. For source-only behavior a screenshot cannot prove the outcome; use the linked source/probe. No user desktop was controlled.

## Styles and content

| Requested item | Result | Evidence / limit |
|---|---|---|
| Shaded and textured | Same modes/ordinary material placement; opacity differs | baseline/shaded crops; G07–08,18,31 |
| Hidden line / monochrome | Same mode availability and color control | hidden_line/monochrome/colors crops |
| Wireframe | Same mode availability; edge reconstruction differs | wireframe crop; G14 |
| X-ray / ordering | Differs | G27; no arbitrary intersecting-glass sort stress test |
| Back edges | Present in both; visual dash/raster differences remain | [pair](crops/synthetic-back-edges-back-edges.png); no claim of pixel identity |
| Profiles | Present; soft seams incorrectly restored | [off](crops/smooth-profiles-off.png), G14 |
| Edge width | 4 px export control present in both; not physical HiDPI validation | [pair](crops/synthetic-width4.0.png) |
| Edge color all-same | Present | [colors](crops/synthetic-colors.png) |
| Edge color by material | N/A reference feature deferred | core/style.py docstring, no active control |
| Front/back face color | Present | colors/monochrome; alpha/lock treatment differs |
| Sky / ground / horizon | Same basic backdrop | [low pitch](crops/synthetic-pitch5.0.png); no terrain suppression test |
| Background color | Same control | flat crop |
| Fog / watermark | N/A neither implemented in inspected GL paths | Not inserted into fixture as inert invented fields |
| Sun and ground shadows | Missing-on-Metal | G12 |
| AO presence and look | Present, differs | G28; foliage-mask source gap |
| MSAA edge quality | Differs at 1× | G29, no physical 2× capture |
| Smooth faces / soft edges | Smoothing implemented; soft profile seams differ | cylinder + profiles-off, G14 |
| Material transparency / alpha texture | Differs | G07,18 |
| Layer opacity / locked fade | Differs | G08,15 |
| Color by tag | Fixed route retained; tag opacity/fade still differ | by-tag crop + pack tests; no re-report of repack fix |
| Section cut/cap/hatch/boundary | Present, paired | section and section-parallel; cuts are not inert |
| Section active/inactive widget | Present; interaction missing | baseline, section-tool; G02 |
| Guides and guide points | Missing when annotation gate off; through-model line behavior differs | guides-only/baseline; G03,17 |
| Dimensions / leaders / text | Same sampled live layout, missing export overlays | baseline versus export-overlays; G16 |
| 3D text | Same generated nested geometry | baseline 3D letters |
| Image planes/imported pictures | Missing-on-Metal | G06 |
| Tiles / terrain / photo mesh | Missing-on-Metal by source inspection | G13; no geographic image fixture |
| Survey points/surfaces/path overlays | Partial: draw_annotations calls paths, not points/surfaces; annotation gate applies | S: wgpu_mesh_tools.py:252 vs viewport.py:10623–10852; geographic display belongs in P5 |
| Hidden geometry and hidden objects | Missing/different reveal | G10 |
| Mirrored/scaled instances | Same sampled shape; glass differs | mirrored green box with scale(-1,1,1.5) |
| Nested components / linked content | Same overview placement; not every child verified | four read-only model pairs, text nested children; no link refresh/write |
| Scale figure mesh variant | Same quad marked mesh; complex mesh variant U | mesh-figure-live; UV result shared, not a new regression |
| Texture positioning preview | Command/material preview tests pass; full visual pins/drag U | test_wgpu_texture_position.py, 30 QImage deprecation warnings |

## Interaction, camera and lifecycle

| Requested item | Result | Evidence / limit |
|---|---|---|
| Edge / face selection | Missing-on-Metal cue | G01, selected-edge + selected-face |
| Group / nested selection | Group cue differs; nested visual selection U | G20; existing selection/context mapping tests pass |
| Hover edges / faces / groups under Select | Loose-edge cue differs; face hover intentionally absent in GL Select and Metal; group context scope fix retained | G01, hover-edge/hover-group crops; prior hover-face injected state was not reachable via Select and is excluded |
| Hover under other tools | Uses shared hover callback and mesh outline path; full visuals U | P tool tests + S NativeTools.hover; no assertion that fixed Select-only gating regressed |
| Edit context fade / dashed box | Differs | G11; GL's direct scene.begin_group_edit fixture does not exercise all main-window edit side effects |
| Inference colors / glyphs / dotted lines | Differs | G23 glyph painter sheet; uses actual functions, not a hand-drawn approximation |
| Endpoint/midpoint/on-face/axis locks | Basic native rules tested; candidate scope differs | test_wgpu_interaction; G25; physical lock flow U |
| Rubber bands / measurement labels | Generic primitives implemented; full GL lock/value label look differs | S mesh_feedback/NativeTools.hover, G22–24 |
| Orbit pivot marker | No independent visible marker found in inspected GL overlay; pivot math tested | _orbit_pivot_at and test_middle_gesture_matches_gl; physical gesture U |
| Zoom-window rectangle | Differs visually; projection update tests pass | zoom-window crop; G26 |
| Window/crossing box selection | Differs behavior + look | behavior-probe.json; G05,26 |
| Right-click context menu | Source-confirmed target resolution differs; real popup U | G21, no popup opened |
| Double-click group edit | Routed, but uses picked leaf directly, not context_placement | S wgpu_view.py:767–786; nested ancestor case U (not accepted as parity) |
| Escape / Space | Escape cancel/undo tests pass; real global Space switch U | mesh/update tests; source key forwarding |
| Cursors and modifiers | Existing fixed mirroring retained; Paint Alt/Tape Ctrl physical display U | _apply_tool_cursor and _mirror_cursor inspected, no re-report of known fix |
| Keyboard shortcuts while hovering | Source key forwarding; focus/hover shortcut delivery U | no desktop input |
| Pinch / scroll / two-finger orbit-pan preferences | Wheel math tests pass; physical trackpad U | No NativeGesture-specific handler found in either inspected view; shared OS delivery not assumed |
| Inverted orbit preference | Branch reads source._invert_orbit_y | S wgpu_view.py:666; physical preference toggle U |
| File drag/drop | U | Both bare widgets acceptDrops false; parent-window routing not established |
| Dock drag/drop | GL has explicit dock handlers; Metal lacks them | S, integration acceptance U rather than asserted file-drop regression |
| Tooltips | U | No interactive tooltip acceptance in unshown widgets |
| Parallel / two-point / FOV | Shared camera tests + paired projections | parallel/two-point; FOV changes not separately captured |
| Zoom extents / selection / window | Shared camera + window test; full action routing U | current source retained, no real menus |
| Saved views / scenes / transitions | Basic sheet/recall paths tested; transition animation U | sheet tests; actual composer UI U |
| Standard views / first-person | Shared camera tools tested; each standard view angle U | last-tier camera tests |
| Near/far clipping | U | GL updates depth_reach in paintGL; Metal does not call _sync_depth_reach. Shared-camera sequential capture can mask this, so no parity claim |
| HiDPI widths | U | All captures explicitly 1000×700 at scale 1; 4-px export is not device scale 2 |
| Resize / dock / tabs | U | Would require a mapped native session; no screen takeover |
| Sheets/composer | Offscreen API exposes G09/G16; ordinary sheet tests pass | No A3 GUI capture; viewport/export distinction explicit |
| First frame / latency / memory / flicker | Bounded offscreen timings only; sustained flicker U | measurements.md; no live presented latency claim |

## Tool dispatch audit

Every class in the actual `TOOL_DISPATCH` appears below, plus SectionPlaneTool. **None is certified identical over click/hover/preview/commit/undo for all states.** “Command check” means existing focused tests exercise synthetic clicks/value inputs, commit/cancel/undo (specific test details vary); some tests mock picking. Real GPU visual tool previews and the complete modifier matrix remain open. All 162 focused tests passed. The narrow no-screen audit does not substitute for dogfooding.

| Tool | Native route | Sample / current parity conclusion |
|---|---|---|
| SelectTool | select | P camera; modifier contract fails G19; V face/edge/group/box cues differ (G01/05/19/20). |
| TapeMeasureTool | tape | P shared two-point measurement, Escape; reference pickers return None (G03). No guide-reference parity. |
| MoveTool | move | P loose and group preview/commit/undo/cancel; Ctrl group copy probe fails (G04). |
| LineTool | mesh | P click/result/direct-tool comparison, undo/redo, nested/loose contexts; VCB/real hover all-state U. |
| RectangleTool | mesh | P direct-tool result, undo/redo and numeric dimensions/units; full preview visual U. |
| PushPullTool | mesh | P numeric commit/cancel/undo in loose and nested mesh; suppression/preview gap G22. |
| EraserTool | mesh | P stroke commit on release and restore; guide picker is None (G03). |
| RotateTool | mesh | P loose direct-result/undo, placement preview cancellation; full modifier/visual U. |
| ScaleTool | mesh | P grips, numeric commit, cancel and undo; real GPU box/OBB picking U. |
| OffsetTool | mesh | P numeric undo/cancel; live preview depth U. |
| CircleTool | mesh | P direct shared-tool geometry/undo; glyph/tangent scope G23/25. |
| PolygonTool | mesh | Dispatch inspected; dedicated native end-to-end sample U. |
| ArcTool | mesh | P radial direct shared-tool geometry/undo; tangent scope G25. |
| PaintTool | mesh | P face history + container update without rebake; physical Alt eyedropper/cursor U. |
| TexturePositionTool | mesh | P live material preview, cancel and active route; actual rendered pin-drag visual U. |
| DimensionTool | mesh | P creation/undo/cancel, V live annotation; export G16. |
| TextTool | mesh | P creation/undo/cancel, V live leader; export G16. |
| FollowMeTool | mesh | P preselected-path commit/undo; material/depth preview differs by source (G22). |
| FreehandTool | mesh | P stroke creation, commit and Escape; GPU visual U. |
| RotatedRectangleTool | mesh | P native/direct creation/undo; GPU visual U. |
| ThreePointArcTool | mesh | P native/direct creation/undo; GPU visual U. |
| CenterArcTool | mesh | P native/direct creation/undo; GPU visual U. |
| PieTool | mesh | P native/direct creation/undo; GPU visual U. |
| FlipTool | mesh | P editing/cancel; tool draw_overlay gating G24. |
| FilletTool | mesh | P editing/cancel; full pick/preview matrix U. |
| ProtractorTool | mesh | P guide creation/cancel and rasterized guide test; committed guide gate G17. |
| GeoPathTool | mesh | P editing/cancel; geographic surfaces/points missing from annotation callback. |
| ChangeAxesTool | mesh | P editing/cancel; axes rendering fix retained. |
| ScaleManagerTool | mesh | Dispatch inspected; actual dialog/value flow U. |
| PositionCameraTool | mesh | P shared camera steps/modifiers; model History unchanged; physical UI U. |
| WalkTool | mesh | P shared camera steps/modifiers; crosshair overlay gate G24. |
| LookAroundTool | mesh | P shared camera gestures/modifiers; physical mouse-look U. |
| FirstPersonTool | mesh | P camera and shortcut claims, timer ownership and focus-loss stop; native focus UI U. |
| OuterShellTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| UnionTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| SubtractTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| TrimTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| IntersectTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| SplitTool | mesh | P solid click result and undo against direct shared-tool path; picking mocked, full interactive preview U. |
| SectionPlaneTool | **inert** | V preview absent, P not in dispatch; click/commit unavailable. Existing cuts still render. |

Focused invocations (each timeout ≤120 s; no full test suite):

- `tests/test_wgpu_remaining_tools.py tests/test_wgpu_mesh_tools.py tests/test_wgpu_last_tier.py tests/test_wgpu_tool_coverage.py tests/test_wgpu_texture_position.py tests/test_wgpu_section_caps.py`: **76 passed**.
- `tests/test_wgpu_interaction.py tests/test_wgpu_billboards.py tests/test_wgpu_sheets.py tests/test_wgpu_style.py tests/test_wgpu_scene.py`: **63 passed**.
- `tests/test_wgpu_updates.py`: **23 passed**.

Raw test logs and command capture manifests live in `raw/`. Known fixes from the brief were not re-listed unless a distinct remaining defect was actually evidenced (billboard export and axis occlusion).
