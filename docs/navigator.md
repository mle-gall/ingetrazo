# Navigator spike

**Superseded on 2026-11-10.** The [Structure dock](project-structure.md)
replaced the Navigator UI. The facet index, bridge tools and saved display
expressions documented here remain in use.

## Filter JSON

`core.facets.build(scene)` returns an insertion-ordered index keyed by placed
group UID. Its cache key is `(id(scene), scene.version, len(scene.groups))`.
`evaluate(index, filter)` returns UIDs in outliner order. Null matches everything.

```json
{"all": [
  {"facet": "class", "eq": "IfcColumn"},
  {"facet": "system", "in": ["launch"]},
  {"not": {"facet": "linked", "eq": true}}
]}
```

Boolean nodes are `all` and `any` arrays, or `not` with one child. A leaf has
`facet` and exactly one operator: `eq`, `in`, `glob`, `exists`, `gt` or `lt`.
Glob is case-insensitive; numeric comparisons exclude booleans. List facets
match if any member matches. `exists` considers null, empty text and empty
lists absent. `{"text":"*launch*"}` matches name or ancestor path. An empty
`all` matches everything; an empty `any` matches nothing. Malformed operators
raise ValueError, even on an empty model. Unknown facets are absent.

Facets: uid, name, path (ancestor names separated by `/`), path_uids, depth,
definition (placement name plus a session mesh identity), instance, tag,
tag_uid, tag_folder, hidden, linked, link_source, class, predefined_type,
`kind:<classification-system-key>`, system, type, storey, status, material,
problems. Discipline is `kind:discipline`, not a second classification system.
Storey falls back to the nearest spatial ancestor's name. Status comes from a
Common pset. Material uses the record name, otherwise greatest face area per
material. Material geometry and validation counts are computed only when
requested; the dock explicitly asks before computing face material fallback.
`values(index, facet)` counts each placement once per distinct list member.

## Views, rules and display

The registry accepts these additive JSON sections:

```json
{
  "views": {
    "launch": {"name": "Launch", "filter": {"facet": "system", "eq": "launch"},
               "color_by": "kind:discipline", "isolate": true}
  },
  "rules": {
    "review": {"name": "Review columns", "filter": {"facet": "class", "eq": "IfcColumn"},
               "apply": {"patch": {"description": "Reviewed"},
                         "classifications": [{"system": "discipline", "code": "S", "name": "Structural"}]}}
  }
}
```

Registry validation checks filter syntax and entry shape. Rule application
validates every resulting record before executing one CompoundCommand of
SetRecordCommands. Classifications merge by `(system, code)`; linked placements,
including descendants of linked containers, reject the whole operation.
Rules run explicitly; this spike does not install an automatic change listener.

`viewport.view_filter` is a UID set or None. Isolate includes matched placements
and descendants; it does not resurrect hidden objects or hidden tags. Loose
geometry is unaffected. Hide results uses exact complement membership rather
than inherited inclusion, so an unmatched ancestor cannot reveal its matched
child. This is an explicit exception to isolate's subtree semantics. Previous
view restores up to ten prior filter/colour states, including this distinction.
Display changes use `bump_view`, not document history. They clear at New/Open.

`viewport.view_tint` holds RGB tuples, inherited by descendants without their
own value. SHA-256-derived categorical colours are stable across sessions.
The by-layer material path overrides face materials in textures/shaded/xray;
wireframe and technical flat modes retain their own appearance. Layer hiding
and locking still apply. Selection/picking consult the same allowed-UID set. Excluded group selections
are dropped. A filter exits an excluded editing context so its working mesh
cannot remain visible through the loose-geometry pass; pending component edits
use the normal edit-exit share-back behavior. The shared placement list is
filtered after expansion, so hidden-object ghosts obey the same scope.

Saved scenes have an optional `navigator_view` registry key. ScenesPanel recalls
it after the camera/layers. Missing keys and older scenes leave the Navigator
state unchanged. Composer callers of SavedView.apply do not yet resolve this
key; they need the same registry-to-display hook. Unsaved ad hoc filters are
not captured by scenes.

## Archived dock interactions

Search treats plain text as a substring and accepts explicit globs. Checked
values are OR within a facet and AND across facets. Counts exclude that facet's
own clause so another OR choice remains reachable. Facets show the first 50
values and a text field for finding more. `(missing)` selects absent facts.
Results group by definition, page
1,000 definitions at a time and create placement children on expansion.
Selection follows loaded result rows and opens their containment context, using
the Outliner’s sibling-selection rule. Select all includes all matching groups
across contexts for bulk metadata operations.

Toolbar actions select, isolate, hide, clear, colour, classify using RecordDialog,
assign an existing tag, save/apply a rule, or export. Right-click editable facet
values to apply to selection in one history step. Rule saving and applying are
two undo steps (registry definition, then one atomic classification step).

## Agent tools

Bridge tools: query_facets(filter, facets), query_view(filter, offset, limit),
set_view_filter(filter, color_by), save_view(key, name, filter, color_by, isolate),
apply_view(key), set_rule(key, value), apply_rule(key). Query rows expose UID,
name, path, class, kinds, tag and hidden. Page limits are 1–1,000. Null clears the
display filter. Applying a non-isolating saved view changes colour but leaves
all groups eligible for drawing.

Export profiles accept `filter` with the same JSON language. The IFC exporter
includes only exactly matching grouped objects; it does not implicitly include
descendants. Loose tagged faces are excluded from a filtered export. The spike dock
saved a `navigator` export profile before calling save_ifc. Export is independent
of the current display filter. Spatial scaffold is still generated by the IFC
exporter. User-defined profile keys should be used for durable workflows.
