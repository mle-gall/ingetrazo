# Navigator validation ledger

The complete 24-batch run finished with **6,880 passed, 19 failed, 322 skipped,
2 xfailed, 805 deselected and 56 warnings**, in 4,035 s. Eighteen failures match
the supplied baseline. The additional catalog-worker timeout passed its isolated
recheck; the baseline swatch-tooltip failure did not recur. The default
six-batch attempt was interrupted, as detailed below.

The last focused check of the changed Navigator/rendering paths passed
**23 tests, with 1 skipped**, in 2.47 s. Several fixes landed during or after the
full run; these focused checks cover them. The full result is not an immutable
snapshot validation of the final commit.

All commands ran inside the spike worktree, with its `.venv-work` interpreter.
No repository was pushed and no remote collaboration objects were created.

## Final focused checks

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_navigator.py tests/test_agent_record_tools.py tests/test_saved_views.py tests/test_ifc_export.py tests/test_sidebar_trays.py tests/test_move_keeps_buffer_offsets.py -q
```

58 passed, 1 skipped in 13.40 s. Covers filter operators, counts, linked rule
rejection, atomic undo, inherited visibility, previous exact-complement state,
face-material override, nested proxy identity, scene-key persistence, agent
paging and saved views, missing-value navigation, filtered IFC output, existing
saved views and sidebar behavior, and pick-buffer reuse.

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_agent_tools.py tests/test_object_record.py tests/test_object_record_schema.py tests/test_ifc_records_export.py -q
```

41 passed, 13 skipped in 6.30 s.

After the placement-page cap, Outliner context selection, Show all/Previous view control synchronization, and document-boundary history clearing:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_navigator.py -q
```

16 passed in 11.76 s. The control-synchronization check previously passed 15
tests in 16.60 s; the context-selection check passed 15 tests in 6.60 s; the
placement-page check passed 14 tests in 0.77 s. Offscreen tests do not establish GPU frame latency or
interactive rendering quality.

## Earlier focused runs

Each line below used the prefix
`QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest` and suffix `-q`.

| Modules | Result |
| --- | --- |
| tests/test_navigator.py tests/test_agent_record_tools.py | 16 passed, 2 failed initially: missing Group import and undefined system in the test fixture; both corrected |
| tests/test_navigator.py tests/test_agent_record_tools.py tests/test_saved_views.py tests/test_ifc_export.py | 35 passed |
| tests/test_navigator.py tests/test_sidebar_trays.py | 21 passed |
| tests/test_navigator.py tests/test_agent_record_tools.py tests/test_saved_views.py tests/test_ifc_export.py tests/test_sidebar_trays.py | 51 passed |
| tests/test_navigator.py | 11 passed before additional bridge/dock/export tests |
| tests/test_move_keeps_buffer_offsets.py tests/test_sidebar_trays.py tests/test_navigator.py | 28 passed, 1 skipped after the full-run regressions were corrected |

## Full-suite interpretation

The bounded run used exactly:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow'
```

It started before the final fixes. Its first batch caught two new regressions:
`test_the_lazy_pick_table_is_kept_on_pick_up_and_its_rows_follow_a_drop`
(the Navigator epoch field shifted positional fields), and
`test_a_first_run_opens_the_everyday_trays_and_keeps_the_rest_ready`
(the new dock initially disturbed first-run tab order). The epoch field now
appends to the existing header and Navigator starts hidden. Both tests pass in
the focused rechecks above. The full run must not be described as a clean run
of the final tree: subsequent fixes were checked with focused modules.

The supplied baseline identifies 19 pre-existing failures: 14 translation cases
including Arabic, cursor picking, extension wrapping, hidden panels, swatch
tooltip and toolbar bold. Those are outside this spike and were not repaired.


The six-batch run was interrupted during batch 3 after that batch exceeded
28 minutes wall time (about 9.5 minutes CPU, roughly 2 GB resident memory).
Completed batches: batch 1 had 17 failed, 1,006 passed, 77 skipped; batch 2 had
1,303 passed, 53 skipped. Only this worktree's runner and child were terminated.
Those partial counts are **not** a full-suite result.

The complete test set was then restarted with smaller process batches, without
changing the test marker or omitting any modules:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/pytest_batches.py -m 'not slow' --batches 24
```

The restarted run also reported
`tests/test_extension_manager.py::test_extension_sort_modes_and_recent_date_availability`,
which is not in the supplied baseline: its catalog worker was still present at
the test's 15-second deadline. The isolated recheck passed:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_extension_manager.py::test_extension_sort_modes_and_recent_date_availability -q
```

1 passed in 8.62 s. This remains an additional full-run failure; the isolated
pass does not establish its cause. No extension implementation was changed.

The dock control synchronization and document-boundary clearing fixes were made
during the 24-batch run and checked with the final 16-test Navigator command above. The full-run counts and the final
focused check are separate evidence; do not describe the full run as an immutable
snapshot of the last commit.


Final rendering-state regression check:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_navigator.py tests/test_move_keeps_buffer_offsets.py -q
```

22 passed, 1 skipped in 3.09 s. This covers the final shared-placement filtering
(ghost passes cannot receive excluded placements), leaving an excluded working
mesh, and dropping excluded group selections. The first working-mesh test
attempt failed because its bare Viewport had no MainWindow status bar; the test
fixture now stubs status messages. That initial attempt had 21 passed, 1 skipped,
1 failed. The preceding ghost-only check had 21 passed, 1 skipped in 4.00 s.
These final rendering-state fixes were also made during the full run and are
covered by this focused command, rather than a claim that the full run used one
immutable source snapshot.


## Completed full-run failure comparison

Baseline failures that recurred:

- Translation completeness: ar, de, id, it, ja, ko, lo, pl, pt-BR, ru, th, uk,
  vi and zh-CN (14 cases).
- `tests/test_dimensions.py::test_world_under_cursor_uses_cached_pick`.
- `tests/test_extension_manager.py::test_long_author_tags_and_license_wrap_within_preview_width`.
- `tests/test_panel_refresh_deferred.py::test_hidden_panels_let_the_previous_document_go`.
- `tests/test_tooltips_wrap.py::test_an_extensions_toolbar_added_after_start_up_shows_names_in_bold`.

Additional full-run failure:
`tests/test_extension_manager.py::test_extension_sort_modes_and_recent_date_availability`.
It passed in isolation; its cause remains unestablished. The supplied baseline's
swatch-tooltip failure did not recur. Equal total failure counts (19) therefore
do **not** mean identical failure sets.

The final membership-colour normalization check used the same last focused
command:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python -m pytest tests/test_navigator.py tests/test_move_keeps_buffer_offsets.py -q
```

23 passed, 1 skipped in 2.47 s. It additionally verifies that membership order
and duplicate codes cannot change categorical colours, and singleton lists use
their value's colour.

Read-only measurement command:

```sh
QT_QPA_PLATFORM=offscreen .venv-work/bin/python scripts/measure_navigator.py
```

See `navigator-spike-findings.md` for the measured stages and their limits.
