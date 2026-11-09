# Metal selection on the ride model

The five-point run used `space_asbuilt_ride.igz` with its linked document, the shared document camera, a 1574 × 1095 logical viewport, and 76,029 resident rows. Group 1 covered 49,195 rows. The starting revision was `aa9df698`.

| Operation | OpenGL reference | Metal before | Metal after |
| --- | --- | --- | --- |
| Enter Group 1 | 11.87 s to the depth-1 log | 22.55 s in the deferred repack | 18.8 ms double-click dispatch, 173 ms first frame, zero repacks |
| First click inside | Space Mountain Paris - Ride | Empty selection | Space Mountain Paris - Ride, 259 ms profiled dispatch |
| First Esc | 9.84 s to the root log, including two Esc events and waits | 32.44 s in the repack | 167 ms first Esc dispatch, depth 0, zero repacks |
| Group 1 click at P0 | 47.42 s | 21.95 s | 0.92 s including the harness wait, 199 ms dispatch |
| Group 1 click at P2 | 10.98 s | 9.13 s | 0.88 s including the harness wait, 183 ms dispatch |
| Group hover | No group mark | 49,195 rows, 27–29 ms for row expansion alone | Zero group rows, 3–18 ms for delivered mouse moves at the five points |
| Blank frame on context change | None reported | Owner observed axes only | Pack and GPU rows retained. Screenshot obscured by another window |

The P0/P2 wall times use the previous screenshot marker and the subsequent selection log. They include the harness's 700 ms settle. The original context traces timed the repack separately, while the GL context logs include settling. Metal's largest measured top-level click dispatch among the five points was 199 ms. The measurements do not bound GPU presentation latency or every deferred Qt callback.

Five serial Metal runs were used, including the baseline profiler run and a shortened diagnostic replay. Baseline hover expansion was also timed without showing a window, using the base revision's actual row resolver and warmed parent map on the same document. The final five-point replay delivered a Qt mouse move at each coordinate to measure hover even when macOS routed the physical pointer elsewhere.

## Where the time went

* In the instrumented baseline P0 click, 48.14 s of the 48.42 s dispatch ran in the Properties tray, with 47.92 s in cut-list generation. Reading the nested parts materialized deferred meshes and measured face areas. A widget below the Properties scroll area still reported itself visible. The Parts panel now waits until exposed to measure and keeps selection in already-listed rows synchronized.
* GL's Select tool suppresses face hover. Its geometry hover painter draws edges and faces and has no group mark. Metal now sends zero hovered instance IDs. It caches selected subtree row lists and checks the selection signature before expanding a selection.
* The bounds key includes the edit stack and active mesh. Metal now discounts world-geometry-preserving context changes, tracks editable world copies separately, and retains the stack dependency when Hide Similar is active. The edit fade/hide still writes instance bits 64/128. Large top-level container boxes are measured during the initial pack, using the same exact geometry routine as GL. Before this change the first edit frame spent 863 ms in the box computation.
* Instance deltas use the same inherited visibility, layer and paint resolution as packing. The existing prototype ID includes mesh identity, baked paint and billboard mode. Changes to a placed matrix or group visibility can update resident rows even in a nested painted model. Changes to geometry in such models, changes requiring a new baked variant, and hidden-stream replacements can still require a synchronous full pack. The previous scene remains presented during packing, with no intermediate empty upload.
* Presenting a current frame alone left the inside selection empty. Faded surroundings still participate in the ID pass. Select now resolves an out-of-context hit with an exact ray query against the editable subtree's resident BVH, with an edge fallback. Picking an open instance uses its editable world copy in world coordinates.
* The five-point run still spent 31.78 s between the double-click screenshot and the inside-click log, including the move, click and waits. A separate diagnostic replay traced the deferred stall to component thumbnail signatures materializing meshes and walking sampled faces. The thumbnail pass now clips against the outer scroll area and schedules new rows when exposed. That final fix was verified offscreen. The post-fix wall interval on the ride model was not remeasured.

## Select facade audit

| Path | Implementation used by Metal |
| --- | --- |
| Single click and modifiers | Shared SelectTool priority, expansion and selection modes. Scene selection, surface and curve expansion use the document model. QWidget update and projection use the visible Metal view. |
| Groups, faces and edges | Native row resolution, context ancestry, inference queries, editable mesh triangle tests and projected edges. Visible-edge arbitration uses `edge_point_under_cursor` bound to Metal projection and native `_is_occluded`. |
| Labels, dimensions, paths, sections and guides | Shared geometric pickers bound to the facade, using its logical dimensions, camera ray, segment clipping, text layout and projection. Drape samples document terrain/survey height. Pick tolerance is a shared preference. |
| Reference images | Shared image-plane intersection and face/image depth comparison bound to Metal's pixel ray. |
| Extension items | Shared registry dispatch passes the Metal facade to the extension's pick callback. Selection state and selection notifications belong to the source document controller. |
| Double-click and Esc | Shared document controller for locks, linked documents, edit history and stepping out. Label/dimension dialogs use the document window and history. The dotted box uses Metal projection, the shared box geometry and the same pixel containment test. |
| Box selection | Both GL-only accelerators are disabled on the facade. The shared model-space traversal projects loose geometry, nested placements, guides and annotations with the Metal camera. Window and crossing selection include occluded geometry. No hidden GL edge projection, pick index, instance chunks or depth buffer participate. |

## Verification

The targeted renderer, interaction, edit-context and billboard run reported `156 passed, 2 skipped, 7 warnings`. The Parts and Components panel run reported `59 passed`. The broader changed-symbol run covered 184 test files in bounded offscreen batches and reported an aggregate of `3 failed, 2113 passed, 30 skipped, 93 warnings`. The extension-card width, hidden-panel lifetime and macOS toolbar shortcut tooltip failures each reproduced on the base revision. The tooltip assertion expected Ctrl+Shift+J and received the native macOS shortcut glyphs.
