# Source evidence index

Inspection is against audit base `69701905`. Renderer sources are unmodified. Links identify the exact current methods; source-only findings are not visual acceptance.

## views/wgpu_view.py

- [set_scene, lines 90–172](../../../views/wgpu_view.py#L90)
- [draw_frame, lines 257–352](../../../views/wgpu_view.py#L257)
- [render_image, lines 371–424](../../../views/wgpu_view.py#L371)
- [hover, lines 453–524](../../../views/wgpu_view.py#L453)
- [sync_selection, lines 526–535](../../../views/wgpu_view.py#L526)
- [contextMenuEvent, lines 750–765](../../../views/wgpu_view.py#L750)
- [mouseDoubleClickEvent, lines 767–786](../../../views/wgpu_view.py#L767)
- [event, lines 788–795](../../../views/wgpu_view.py#L788)
- [wheelEvent, lines 868–872](../../../views/wgpu_view.py#L868)
- [rect_rows, lines 881–887](../../../views/wgpu_view.py#L881)

## views/wgpu_tools.py

- [click, lines 118–164](../../../views/wgpu_tools.py#L118)
- [key, lines 205–242](../../../views/wgpu_tools.py#L205)
- [pick_edge_any, lines 334–335](../../../views/wgpu_tools.py#L334)
- [pick_guide, lines 337–338](../../../views/wgpu_tools.py#L337)
- [pick_axis, lines 340–341](../../../views/wgpu_tools.py#L340)

## views/wgpu_mesh_tools.py

- [set_suppressed_faces, lines 177–179](../../../views/wgpu_mesh_tools.py#L177)
- [mesh_feedback, lines 181–226](../../../views/wgpu_mesh_tools.py#L181)
- [draw_annotations, lines 228–248](../../../views/wgpu_mesh_tools.py#L228)
- [_unsupported_pick, lines 268–269](../../../views/wgpu_mesh_tools.py#L268)
- [_nearby_loose_edges, lines 307–308](../../../views/wgpu_mesh_tools.py#L307)

## views/wgpu_scene.py

- [_source_arrays, lines 84–137](../../../views/wgpu_scene.py#L84)
- [_placement_state, lines 140–170](../../../views/wgpu_scene.py#L140)
- [pack_scene, lines 173–291](../../../views/wgpu_scene.py#L173)
- [_material_columns, lines 294–340](../../../views/wgpu_scene.py#L294)
- [_texture_array, lines 343–364](../../../views/wgpu_scene.py#L343)

## views/wgpu_overlay.py

- [snap_glyph, lines 61–68](../../../views/wgpu_overlay.py#L61)

## views/viewport.py

- [render_image, lines 2284–2364](../../../views/viewport.py#L2284)
- [_draw_selection_box, lines 9872–9893](../../../views/viewport.py#L9872)
- [_draw_zoom_box, lines 9895–9906](../../../views/viewport.py#L9895)
- [_draw_snap_indicator, lines 9927–10041](../../../views/viewport.py#L9927)
- [_context_pick, lines 17956–17984](../../../views/viewport.py#L17956)

## Native shader/pass evidence

- [shading.wgsl](../../../rust/ingetrazo_render/src/shading.wgsl): `face_pixel` alpha threshold and constant output alpha, paint markers and highlight pattern.
- [edges.rs](../../../rust/ingetrazo_render/src/edges.rs): `expand` reconstructs candidate adjacency from resident face stream; source soft/hidden metadata is already absent.
- [scene_bake.rs](../../../rust/ingetrazo_core/src/scene_bake.rs): `prepare` filters hidden faces and hidden/soft hard edges; smooth corner fan normals **are implemented**.
- [lib.rs](../../../rust/ingetrazo_render/src/lib.rs): `render_image` validates temporary rows and rejects matrix changes; default antialias is true. `render(false)` uses an offscreen color target.
- [axes.wgsl](../../../rust/ingetrazo_render/src/axes.wgsl), [ao.wgsl](../../../rust/ingetrazo_render/src/ao.wgsl), [xray.wgsl](../../../rust/ingetrazo_render/src/xray.wgsl).

## Behavioral probes

[probe.py](probe.py) directly calls rectangle mapping and all three Tape reference pickers, the section/image picker stubs, and both actual glyph painters. [Result](raw/behavior-probe.json).

[Move-copy result](raw/move-copy-probe.json) uses `tests.test_wgpu_updates.fixture_scene/Renderer` with the same NativeTools setup as `test_move_preview_commits_only_once`, but sends `Qt.ControlModifier` on both clicks, at `(0,0,0)` then `(2,0,0)`. It leaves group count 2 and commits `MoveGroupCommand`. This establishes the special native group route ignores Ctrl; it does not audit every platform modifier mapping.

Drag/drop acceptance: both bare widgets report `acceptDrops=False` in the probe. GL has dock-specific overrides while Metal does not, but parent integration may matter. This is therefore an **open acceptance item**, not a proven user file-drop regression.

Selection modifier probe: [results](raw/selection-modifiers.json), invokes actual `WgpuView.select_rows` against a selected Group and compares with `Scene.select(mode=tools.select.selection_mode(modifiers))`. Native-only modifier tests are not equivalence tests.
