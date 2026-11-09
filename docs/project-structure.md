# Project Structure

*Design note, 2026-11-09 (Maxence + Claude). Supersedes the Navigator spike
(`navigator.md`): its facet index and agent tools stay as plumbing, its dock goes.*

## Why

A document carries four parallel ways of saying what an element is, and each
one is maintained by hand:

1. **Containment** — groups and components, the Outliner. Geometry's own
   nesting, often meaningless (`Groupe#536`).
2. **Tags** — layers and folders. Visibility and drawing habit.
3. **Object records** — IFC class, predefined type, psets, Status
   (`object-record.md`).
4. **Classifications and the registry** — discipline, ride kinds, Uniclass,
   types, systems, export profiles, IDS (`project-registry.md`).

Tags and classifications say nearly the same thing in different words, nothing
keeps them consistent, and classifying the ride as-built model took one agent
run for records, another for tags, and a human to reconcile both. The Navigator
added a fifth vocabulary (facet filters) on top instead of removing one.

## The idea

**One tree per project, authored by the user, that reads like the domain**
— Ride › Track › Sections, Ride › Supports › Columns, Facilities › Preshow 1 ›
Steel › Beams — is the single source of truth. Each node carries a **recipe**:
tag and folder, IFC class and predefined type, classification codes, system,
type, default properties. An element is **filed** under a node once; the tag,
the record and the classifications are derived from it. Layers 2 to 4 stop
being things you edit and become projections of the structure.

Decisions taken with Maxence (2026-11-09):

- **Tags are derived.** The Layers panel keeps visibility and drawing habits;
  its folders mirror the tree; re-tagging a filed element means re-filing it.
- **The IFC class lives in the node.** A node names one class (and predefined
  type); it may allow a short list, in which case the element picks within it.
- The structure is **core**, not an extension, and stack-neutral JSON
  (`stay-on-fork` decision: schemas must survive a later Rust core).

## Data model

A new registry section `structure` (`core/bim_registry.py` `SECTIONS`), so it
lives with the vocabulary it references and is shared through a project file:

```json
"structure": {
  "nodes": {
    "ride":          {"name": "Ride",     "parent": null,   "order": 0},
    "ride.track":    {"name": "Track",    "parent": "ride", "order": 0,
                      "recipe": {"systems": ["track"],
                                 "classifications": [{"system": "discipline", "code": "S"}]}},
    "ride.track.sections": {
      "name": "Sections", "parent": "ride.track", "order": 0,
      "recipe": {"tag": "Track Sections",
                 "class": "IfcMember", "predefined_type": null, "object_type": "",
                 "classes_allowed": ["IfcMember", "IfcBeam"],
                 "classifications": [{"system": "ride_kinds", "code": "TRK"}],
                 "type": "track_section",
                 "psets": {"Pset_MemberCommon": {"Status": "EXISTING"}}}}
  },
  "active": "ride.track.sections"
}
```

- Node keys are stable strings; `name`, `parent`, `order` give the tree.
  Renaming a node never changes its key. Deleting a node with members is
  refused unless they are re-filed or `force`.
- **Recipes inherit down the tree**: scalars (`class`, `predefined_type`,
  `object_type`, `type`, `tag`) take the nearest ancestor's value; lists
  (`classifications`, `systems`) are the union, deduplicated by `(system,
  code)` and key; `psets` merge by property name, child wins.
  `resolve(registry, key)` returns the effective recipe.
- **Tag** defaults to the node name; **folder path** is the names of the
  ancestors. `tag`/`folder` in a recipe override only when an existing layer
  must be kept (the ride's `Track Sections`).
- `class: null` means "no IFC record" (reference planes, construction lines):
  the element is still filed, tagged and counted, and never exported.
- **Membership** is stored once, on the group: `group.ext["structure"] =
  {"node": "<key>"}` (`Group.ext` already carries `link`). Not in the record,
  because filed elements may have no record. Component instances are filed
  individually (they own their records), with a helper to file "all instances
  of this definition".
- Linked groups are read-only: their structure is the source document's,
  **mounted** under a node `link:<stem>` whose children mirror the source tree,
  the way linked tags are mirrored today (`links.tag_name`).

## Engine (`core/structure.py`)

Pure functions over `scene` + registry, returning History commands so every
action is one undo step:

| Function | Does |
| --- | --- |
| `resolve(registry, key)` | effective recipe, inheritance applied |
| `file(scene, uids, key)` | `CompoundCommand` of: set membership, `EnsureLayers`/`AssignLayerCommand` to the node's tag (folder created), `SetRecordCommand` patch that sets the node-owned fields (class, predefined type, object type, type, systems, the node's classifications, pset defaults only where the element has no value); keeps name, mark, description, guid, quantities and foreign classifications. Refuses linked uids and classes outside `classes_allowed`. |
| `unfile(scene, uids)` | removes membership; leaves tag and record as they are (explicit choice; the element becomes *unsorted*). |
| `resync(scene, keys=None)` | after a recipe edit: re-derives tag and node-owned record fields of every member; reports what changed. |
| `members(scene, key, recursive=True)`, `node_of(group)` | reads. |
| `unsorted(scene)` | top-level own groups without membership, plus filed groups whose record contradicts the node (class outside the allowed list). |
| `completeness(scene, registry)` | per node: members, members without record, missing Status, IDS requirement hits when a profile names an IDS; the "problems" view of the tree. |
| `bootstrap(scene, registry)` | proposes a structure from what exists: one node per layer folder and layer (the ride files organised on 2026-11-09), recipe inferred from the members' records (majority class, the classifications and systems shared by all members), files every tagged group; returns the proposal and a conflict list without applying. |

Record ownership rule: the node owns `class`, `predefined_type`,
`object_type`, `type`, `systems` and the classifications whose `system` the
node names; the element owns everything else. `resync` only touches
node-owned fields, so per-element Status edits survive.

## Agent tools (`core/agent_structure.py`, registered in `agent_tools`)

`query_structure` (tree with counts, resolved recipes, active node),
`set_structure` (replace or patch nodes; validates recipes against the
registry vocabulary), `file` (uids → node, one undo step),
`query_unsorted` (paged), `bootstrap_structure` (proposal, then `apply=true`).
An agent classifies by choosing nodes; `set_record`/`tag` stay for the
exceptions.

## Panel (Phase 2) — replaces the Navigator dock

- One tree with counts, the active node highlighted; click = select
  members, double-click = isolate, right-click = colour by node, show/hide.
- **Unsorted** at the bottom with its count; drag rows from the Outliner or
  the viewport selection onto a node to file them.
- Recipe editor on a node: class picker from the project vocabulary,
  classifications, system, Status default.
- Problems badge per node from `completeness`.
- The Layers panel's folders mirror the tree; editing a filed element's tag
  in Entity Info offers "re-file under…".

## Modeling integration (Phase 3)

The **active node** replaces the active tag: new groups, Insert, Link, Paste
and 3D text are filed under it on creation (GL and Metal paths alike). Entity
Info shows the node path. Scenes may remember an active node.

## Templates and IDS (Phase 4)

Templates (ride; building by storey and trade; infrastructure) seed a tree
with recipes. An IDS attached to an export profile drives `completeness` and
can propose recipe fields (required psets) per node.

## Migration of the ride files

`bootstrap` on `space_asbuilt_ride.igz` (tags organised 2026-11-09, records
from 2026-11-08) should yield Ride › {Track, Supports, Access, Fasteners,
Reference, Context} with recipes inferred from the records; facilities and
stairs mount under their links. Conflicts to expect: the `_To review` layers
(no class), fasteners (tagged, no records, `class: null`), Groupe#536.

## Phases and acceptance

1. **Engine + tools** (this note's data model, `core/structure.py`,
   `agent_structure`, registry validation, `bootstrap`): tests on a synthetic
   scene and on a headless load of the ride; a `bootstrap` report for the ride.
2. **Panel** replacing `NavigatorDock`; the facet index stays for queries.
3. **Modeling integration**: active node on creation, Entity Info, re-file.
4. **Templates and IDS.**

Out of scope: any change to the IFC exporter (it reads records as today) and
to the `.igz` geometry format.
