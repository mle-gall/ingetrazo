# Navigator spike findings

## Measurements and evidence

Read-only fixture: `/Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz`.
Measured with Python 3.13, Qt offscreen, using `scripts/measure_navigator.py` in
the isolated worktree interpreter. No changes were made to the fixture.

| Operation | Seconds | Notes |
| --- | ---: | --- |
| Load fixture | 8.287 | Second load; OS file cache warm |
| Index | 1.041 | 91,211 placements; lazy material/problems |
| Evaluate null | 0.008 | 91,211 results |
| Evaluate class = IfcColumn | 0.019 | Zero results |
| Evaluate text = *launch* | 0.214 | 11,085 results |
| Evaluate structural AND system exists | 0.039 | Zero results |
| First facet tree | 0.597 | Offscreen Qt widgets, final grouping/counts |
| Change class filter | 0.214 | Empty result set |
| Set isolate display state | 0.148 | Does not include GPU upload/frame latency |

The supplied file loaded **no group IFC records**: class/system counts were
empty. The reported 1,482 classified records were therefore unavailable in this
on-disk fixture. They may exist in an unsaved live document; this experiment did
not inspect or alter that application. These numbers establish metadata/tree
performance, not classified-workflow performance. A classified fixture must be
saved separately by its owner before the latter can be verified.

The measured evaluator cases meet 0.3 s and index meets 5 s. Arbitrarily large
boolean expressions, lazy materials and validation are not bounded to 0.3 s.
Material fallback can instantiate deferred meshes and freeze the UI. It needs
incremental work or extraction from deferred geometry arrays before production.
First paint, GPU recolouring and interactive picking latency remain unmeasured.
The dock groups all results before paging definitions and counts checked
facets without their own clause. An earlier cold load took 34.068 s.

## Five task walkthroughs

These are explicit interaction estimates, **not observed usability trials**.
Assume the relevant vocabulary values are visible, no saved view yet, and panels
start closed. Count a click to open a panel, expand a facet, choose a value or
invoke an action. Text entry and file-dialog confirmation are listed separately.
Existing panels have no general intersection of record classifications and tree
selection; their totals depend on placement count, so claiming fixed counts for
those tasks would be misleading.

| Task | Existing panels | Navigator |
| --- | --- | --- |
| Find launch support columns | BIM inspection plus Browser selection; 2 panels, at least 4 navigation clicks plus per-object verification | 1 panel, 7 clicks: open, expand/choose system, class and kind; 8 with Select all |
| Hide everything but structural | Tags plus BIM/Browser when discipline is not already a tag; 2–3 panels, at least 4 clicks plus selection/classification work | 1 panel, 4 clicks: open, discipline expand/value, Isolate |
| Colour by discipline | Requires translating discipline into tags and enabling colour by layer; Tags and BIM, at least 5 clicks plus assignments | 1 panel, 3 clicks: open, colour combo, discipline choice |
| Find untagged objects and classify | Browser/Tags finds untagged placements; BIM edits their record; 2–3 panels, at least 5 clicks plus selection | 1 panel, 5 clicks before dialog editing: open, tag expand/value, Select all, Classify; at least 2 dialog clicks |
| Export only track system | Agent/export profile or manually curated export selection; no equivalent one-panel intersection | 1 panel, 4 clicks before file dialog: open, system expand/value, Export; one confirmation |

“Untagged” must be stated precisely: no visibility tag and no IFC record are
different facts. The tag facet handles the former; `class exists false` handles
the latter through the shared agent/filter API or the class facet’s `(missing)`
checkbox. Both meanings remain visible rather than being conflated.

## What unification exposes

* Imported tag identity, folders, inherited tags and visibility are useful source
  facts. Preserve them for import/round-trip fidelity. Do not silently convert
  tags into record classification codes: many tags mean presentation or editing
  context rather than object semantics.
* Filter visibility currently intersects legacy hidden flags and layer state.
  A matching result may therefore remain invisible. Navigator needs “why hidden”
  explanations and an explicit temporary override before it can replace Tags.
* Isolate is subtree-inclusive, while IFC export is exact-object inclusion.
  Hide needs exact complement semantics to prevent parents revealing children.
  These distinctions need visible counts and previews before saving/exporting.
* A saved scene can reference a view, but composer renderers must resolve the
  reference in their own viewport. A renamed/deleted view needs dependency checks.
  Referenced rules/views also need revision/frozen-result choices for deliverables.
* A faceted selection can span multiple containment contexts. Individual result-row selection follows
  the Outliner’s single-context opening and sibling-selection policy. Select all
  results can still span contexts; subsequent geometry tools need that policy
  reconciled. Result-set record edits do not have this containment restriction.
* BIM takeoff remains document-wide. Pass evaluated UIDs to quantity aggregation;
  never derive quantities from rendered pixels or a partially loaded Qt tree.
* Definition identity is session-local; persistent views should use object facts,
  not the ephemeral definition suffix. Multi-valued colour facets currently use
  a colour per combination, requiring a legend and an explicit conflict policy.
* Rules are saved executable classifications, not continuously running watchers.
  An automatic mode needs cycle detection, dependency tracking and an undo policy.
* The dock's record dialog edits an entire result set atomically, but its ordinary
  command path follows the existing BIM dialog's validation conventions. Rule
  application is stricter and validates every merged record before mutation.

## Recommendation

Make Navigator the primary **discovery and temporary visibility** surface, after
closing the hidden-reason, legend, composer and deferred-material
gaps. Keep tags as a separate persisted mechanism exposed as one facet. Their
presentation and import identities are not interchangeable with record semantics.

Move new discipline/system/kind authoring into object records. Default new
workflow isolation to a saved filter rather than inventing another visibility
tag, while retaining tag visibility for imported models and compatibility.
Replace the three competing navigation lists with Navigator plus a contextual
record inspector. Keep the tree as an explicit containment/edit-context mode,
Tags as an advanced visibility/import manager, Scenes as camera/presentation
snapshots and BIM takeoff as a quantity view over the same evaluated UID set.

This is a useful architectural spike, not evidence that all three panels can be
removed today. The classified ride fixture, real rendering benchmarks and short
observed task trials are the next acceptance gate.
