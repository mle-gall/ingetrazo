# P1 input, selection and capture handoff

Branch: `parity/p1-input-selection`. Local commit only; no push, PR, issue, installed-app launch or mapped capture window. Production edits are confined to the three owned wgpu view/tool files; the merged edit-context fade is unchanged.

## Implemented

- **G02:** SectionPlaneTool dispatch, native projected-frame picking, Select double-click activation toggle, shared Move and History/undo. Qt event tests exercise placement, toggle, move and undo.
- **G04:** all Move operations use MoveTool, retaining resident placement preview methods. Ctrl-copy, external `3x` and internal `/2` arrays and undo are tested. The old separate native group command path was removed.
- **G05/G19:** clicks and directional drag completion use SelectTool and its selection_mode/on_box_select contracts. Window/crossing tests include a group behind a loose face and loose edges. Shift toggles, Ctrl adds, Shift+Ctrl removes; loose-edge picking does not require an ID-buffer pixel.
- **G09:** export temporarily installs billboard matrices through set_instance_world, then restores resident matrices in finally. Default-figure real Metal export succeeds. Success and injected failure restoration have tests.
- **G16/G17/G24 scheduling:** annotation callbacks run without requiring dimensions/text; guides, tool draw_overlay hooks and lock/reference/linear-mode labels are scheduled. render_image(overlays=True) composites the overlay. Export layout remains a P4 integration item below.
- **G21:** context menus use the shared GL _context_pick priority, native context-level groups, and locked_image/locked_group arguments. Locked-group selection and unlock-target delivery have a test. Locked-image picking shares GL's CPU ray geometry; image rendering/unlocked image selection still belong to P5.
- **G22 bridge:** suppression rebakes via pack_scene's existing face_overrides, without changing document attributes or History. Clearing restores the original faces. TexturePositionTool keeps its existing material-preview ownership. Preview faces expose an optional native triangle-stream callback; until P2 supplies it only the outline is drawn (no flat foreground polygon).
- **G10 orchestration:** hidden-geometry and hidden-object flags invalidate the pack. Reveal rendering is not claimed complete.
- **G01/G20 partial visual implementation:** selected loose faces receive cached screen-space dots, depth-tested with the existing native inference BVH; dot colors share GL's front/back color decision. Edges hover light blue and select orange. Groups get orange edges, not native blue face stipple. Group-edge visibility currently uses midpoint occlusion; exact segment clipping/profile/enclosure treatment still needs native integration.

## Verification

- Both crates built in release with worktree-local CARGO_HOME; no target/debug exists.
- New file: **13 passed**, three Qt/QImage deprecation warnings (`tests-new.log`). Tests send QTest click/key events to an unshown widget. Hover uses a real QMouseEvent delivered by QApplication, because macOS QTest.mouseMove uses the OS cursor. Inference is fixed only in command-focused tests; face/edge selection uses the real ray/edge pickers with controlled resident row IDs. Undo is asserted through History, not OS shortcuts.
- Permitted broader invocation, run **once**: **224 passed, 10 skipped, 14 failed** (`tests-focused-once.log`). This is NOT a green broader-suite claim. It exposed missing minimal-facade scene/mark access and an extra texture-suppression refresh; fixes landed afterward and the new tests cover facade Move and texture ownership. The broader tests were not repeated, honoring the once-only instruction.
- Two legacy tests explicitly require obsolete behavior (Shift-add/native group highlight and Section remaining undispatched). Their files and the generated coverage document are outside exclusive ownership. `parent-test-updates.patch` supplies the exact edits for the parent to apply; it is not applied in this branch. The parent must run the affected regressions after integration, including texture positioning, annotations and Move-preview tests.
- All seven requested live-frame cases captured successfully with the audit harness. Crops are GL left / Metal right, 1380×504, each below 1 MB; `crops.json` records source images and coordinates. Additional true `overlays=True` export is in `export/`; default-figure true export is `new-document-*`.
- The only capture stderr is the known first-frame GL sampler warning. No capture exceptions remain in these runs.

## Explicit integration interfaces / TODOs

Exact markers in the owned files:

- `TODO(P2): set_preview_faces accepts world-space triangle float3s;` in wgpu_mesh_tools.py: renderer method `set_preview_faces(float32[N,3,3])`; empty clears. P2 supplies depth/material pass. Suppression already works through pack overrides, so it does not require a renderer identity ABI.
- `TODO(P2): edge-only group flags; face stipple belongs to loose faces.` in wgpu_view.py: remove painter group edges once native selected/hover group flags are edge-only.
- `TODO(P2): replace the cached sampled face marks with a native` in wgpu_view.py: native depth-tested stipple should replace CPU sampling. Current cache avoids repeat work at a fixed scene/camera, but large selections/camera motion have not been performance-certified.
- `TODO(P3/P2): pack hidden-reveal metadata and render ghost/hidden edges.` in wgpu_view.py: view-side invalidation is present; data and ghost/stipple passes are not.
- `TODO(P4): export_annotations(view, painter, width, height) for sheet layout.` in wgpu_view.py: current export scales a logical-view overlay to target size. Different aspect ratios, 2× typography and sheet annotation placement need P4's helper; not exact layout parity.
- `TODO(P4): selection_rectangle(start, end, zoom=False) -> Primitive.` in wgpu_view.py: consumes this helper if available; otherwise uses directional color/dash/fill fallback. P4 should unify the helper signature on integration.
- `TODO(P6): expose pick_edge_any/pick_guide/pick_axis(access, x, y)` in wgpu_tools.py: facade hooks remain stubs pending P6; no competing edits to its file.

## Acceptance still open

G01/G20 exact native look/depth, G10 reveal, G22 depth-tested face preview, and G16 export layout are **partial**, not closed. G11 was already done and is untouched. G03/G25 remain P6; P5 references are not implemented here.

The checked-in audit live_setup injects legacy unstyled Metal rectangle primitives directly instead of exercising mouseMoveEvent. Consequently the box-window/box-crossing crops reproduce that bypass and do **not** certify the new event-path rectangle look; directional selection semantics are covered by Qt tests. The parent/P4 must update the harness injection and recapture before closing G26. Existing P2/P3/P5 material/reference gaps remain obvious in all pairs, so these are convergence evidence, not pixel-equality sign-off. The GL selected-face fixture also selects an obscured slab side; the new standalone visible-face mark test is the direct mark regression.

No physical trackpad, actual popup presentation, installed-app interaction, or OS shortcut undo acceptance was attempted. No changes were made to workflows or other packages' production/test files.
