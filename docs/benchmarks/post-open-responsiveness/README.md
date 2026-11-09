# Metal responsiveness after opening the ride model

Apple M5 Max, 9 November 2026. The supplied harness opened the 141 MB ride model and its facilities link in a new window, activated Orbit six seconds after observing presentation, and sent four hover events. Baseline is the supplied `stall2/stall.log` at `a79de8a9`. After is the fourth and final worktree run.

| Measurement | Baseline | After |
| --- | ---: | ---: |
| Inference `prepare`, worker wall time | 10.060 s | 6.812 s |
| Layer counting, total time inside main-thread callbacks | 4.681 s | 2.609 s |
| Longest uninterrupted count callback | 4.681 s | 170 ms |
| Longest post-picture heartbeat gap outside harness screenshots | 7,760 ms | 232.7 ms |
| Longest post-picture heartbeat gap including screenshots | 7,760 ms | 357.2 ms |
| Orbit activation handler | 1.6 ms | 1.2 ms |
| First hover handler | 184.6 ms | 34.1 ms |

The final run recorded every 50 ms heartbeat from the renderer's first-frame callback (20.01 s) through exit (47.04 s). Its only gap above 300 ms included the harness's synchronous pre-Orbit screenshot. The watchdog sampled the main thread inside `os.system("screencapture …")`. The baseline watchdog sampled gaps above 600 ms. Handler times start at dispatch and exclude queueing.

The layer tally published at 27.21 s. Counting yielded between meshes, so a single weld could exceed the 30 ms slice budget. Worker wall time includes contention during GPU upload and subsequent panel work. It remained above the 2 s target. Camera-grid warming runs on the same worker after the timed `prepare` call.

## Final run command

```sh
cd /Users/legallmaxence/.t3/worktrees/ingetrazo/t3-d5ffbefd
D=/private/tmp/ingetrazo-post-open.ovJkf1
TIMING=1 /Users/legallmaxence/code/ingetrazo/.venv/bin/python "$D/stall_run.py" "$D/run4" /Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz 1 >"$D/err4" 2>&1
```

The scratch harness points ROOT at this worktree, uses a 300 ms watchdog, and logs heartbeat intervals, screenshot boundaries, and the first-frame release time. The scratch timing patch sums the layer panel's count slices and includes final publication.

<details>
<summary>Focused offscreen pytest results</summary>

Each name below denotes <code>tests/test_NAME.py</code>. Each batch used the specified Python interpreter and <code>QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider</code>.

| Files | Pytest summary |
| --- | --- |
| layer_counts_lazy, purge, lazy_mesh_plan, metal_parity_inference, lazy_native_snap, arc_midpoints_lazy, center_inference, wgpu_interaction, wgpu_tool_coverage, wgpu_updates | 118 passed, 3 warnings in 16.08s |
| accent_keeps_widgets, ambient_occlusion, batch_rename, bim_grouped_tags, bim_takeoff_selection_857, bim_takeoff_untagged_moves, boolean_keeps_circles, browser_columns_fit | 65 passed, 8 skipped in 16.24s |
| browser_filter, browser_layer_groups, browser_layer_order, browser_make_unique, browser_material_menu, browser_order_name, browser_side_tree, curve_segments | 110 passed in 26.78s |
| delete_paste_keep_rows, dimensions, edit_context_keeps_rows, entity_info_name, explode_view, extension_manager, eye_lock_on_selection, group_paint_in_model | 2 failed, 101 passed, 1 skipped in 16.09s |
| header_eye_lock_all, in_model_nested, in_model_row_stays_lit, in_model_thumbs_visible, inherited_eye_lock, layer_assignment, layer_undo, layers | 115 passed in 13.26s |
| layers_panel, layers_toolbar, library, links_window, mac_glass, make_group_inside, material_popup, metal_parity_input | 240 passed, 3 warnings in 52.83s |
| metal_parity_integration, object_record, open_replaces_document, outliner, panel_refresh_deferred, parts, pick_index, project_tabs | 1 failed, 215 passed, 2 skipped in 47.48s |
| replace_component, scene_recall_version, scenes_delete_several, select_none, shadows, sheet_tabs, solid_inspector_plugin, startup_first_picture | 124 passed in 21.72s |
| style_editor, tray_scroll_anchor, wgpu_billboards, wgpu_last_tier, wgpu_last_tier_menus, wgpu_mesh_tools, wgpu_remaining_tools, windowizer_example | 102 passed, 1 warning in 2.19s |

The cached-pick, extension-card wrapping, and hidden-panel document-lifetime failures also reproduced individually or together on an archive of the unchanged base commit.

</details>
