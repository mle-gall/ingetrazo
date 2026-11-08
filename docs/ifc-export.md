# IFC export from object records

`formats.ifc.save_ifc(scene, path, project_name="IngeTrazo project",
profile=None, *, project_directory=None)` writes IFC4 by default. A profile is
a key in the project registry's `export_profiles`. IFC4X3_ADD2 is also supported.
The result is an integer-compatible `ExportReport`: existing callers can still
compare or display the count; new callers use `count`, `path`, `problems` and
`ids`. Problems contain object uid, name and messages. Empty scenes still raise
ValueError. When every record is rejected, the file contains a valid project
skeleton and the report has count zero.

The package separates STEP encoding (`step.py`), generated attribute orders
and strict entity construction (`entities.py`), world-space faceted geometry
(`geometry.py`), model traversal (`export.py`) and optional IDS checks
(`ids.py`). No native IFC package is imported to write IFC. Attribute names and
orders are interoperability facts, not copied EXPRESS definitions. Both schemas
have explicit exceptions where their attribute names differ. Tests use
IfcOpenShell as an independent schema and EXPRESS-rule validator.

## Records and relationships

Group records are validated against the selected schema and registry before
export. Invalid records are reported and skipped; unsupported classes instead
have documented substitutes. Their descendants can still export. Record names
default to the group name. Legacy face tags retain their original identity,
class, name and measured quantities.

Occurrence properties use record kinds to select IFC measure types. Enum values
are IfcLabel values. Registry type properties stay on the type; instance properties
are separate overrides. Type resolution supplies default scalar attributes and
system memberships without mutating the record. Only referenced types and systems
are written. Classifications are shared by system and code, including associations
to type objects. If names for the same code differ, the first name wins.

Manual quantities override matching measured quantity names (generic Volume, Area
and Mass also resolve to the corresponding measured class quantity) and carry Description
`manual`. New quantity names containing length, area, volume or weight identify
their dimension; unknown dimensions are reported rather than guessed. Negative
quantities are omitted. Units include metres, square and cubic metres, kilograms
and radians. Quantity CSV and the BIM panel continue using the existing takeoff
implementation.

GUIDs for placed objects are persistent. Types, systems, property sets and
relationships use the document namespace and semantic keys. Geometry edits and
STEP entity-number changes do not change those identities.

## Spatial structure and fallback decisions

The historical Project → Site → Building → Storey skeleton and its stored GUIDs
remain present. Root-level modelled buildings attach to the default site;
root-level storeys attach to the default building. Other objects without a
modelled spatial ancestor attach to the default storey. Modelled sites attach to
the project. Spatial nesting follows the group tree, with untagged groups
transparent. Spaces aggregate into their enclosing spatial structure.

A tagged non-spatial parent aggregates its tagged descendants, crossing untagged
intermediate groups. Only the top-level assembly is spatially contained; its
parts inherit containment through aggregation. Geometry is the group's
world-space geometry minus what tagged descendants claim, matching takeoff.
Spatial groups with faces receive geometry too. Empty tagged containers are
exported. Placements are identity transforms because vertices already use world
metres; storey Elevation records the world origin's z coordinate.

In IFC4, IfcFacility becomes IfcBuilding and IfcFacilityPart becomes
IfcBuildingStorey. In IFC4X3_ADD2, abstract IfcFacilityPart becomes concrete
IfcFacilityPartCommon. The original class is retained in ObjectType.
Unknown occurrence classes become IfcBuildingElementProxy. Unsupported or abstract
type classes become IfcBuildingElementProxyType. General flow segment, fitting and
terminal type bases are abstract, so use a concrete registry class such as
IfcPipeSegment for precise type semantics.

Georeferencing is not implemented. Geometry uses faceted B-reps, open shell
surface models, or indexed polygonal face sets. The view header identifies the
selected view; it does not claim full model-view-definition certification.

## Linked files

Groups placed from a linked document (`Group.ext["link"]`, see `core/links.py`)
and everything under them are skipped, and the report's `linked_skipped` counts
them. A profile with `"include_links": true` exports them with the host. The
linked file is its own deliverable: classify and export it from that file.

## Profiles, provenance and IDS

The UI automatically uses the sole profile or offers a selector for several.
IFC4 ReferenceView writes `ReferenceView_V1.2` in FILE_DESCRIPTION. FILE_NAME
includes the application version, author and organization. Owner history is
written only with author or organization metadata. An organization-only project
uses its organization name for the required person identity.

IDS checks run after writing, only when the selected profile lists IDS paths.
The UI resolves relative paths against the saved project directory. API callers
can supply `project_directory`; without one, paths are relative to the exported
IFC's directory. Each IDS is checked independently, with specification pass/fail
entity counts and status in `<stem>.ids-report.json` and the return report.
Missing IfcTester or unreadable/invalid IDS files are reported without discarding
the IFC. HTML reporting is not included. The UI shows a non-modal report.

Optional developer dependencies are `ifcopenshell` and `ifctester`; tests skip
their consumer checks if absent. The small hand-authored wall handover IDS fixture
requires Pset_WallCommon.Status and a Discipline classification.

## Generated facts and additional relationships

Run `.venv-work/bin/python scripts/gen_ifc_tables.py` with IfcOpenShell installed
to regenerate `core/ifc_tables_data.py`. Runtime export remains pure Python.
Entity and attribute names/order and enum members are interoperability facts.
Never vendor buildingSMART EXPRESS, XML/JSON property libraries or HTML text:
their CC BY-ND distribution terms are incompatible with this GPL codebase.
User-downloaded PSD libraries are read only at runtime (see project registry).

The vocabulary includes concrete elements, spatial objects and groups from
IFC4 and IFC4X3_ADD2. Required enum values use NOTDEFINED where available.
Type counterparts are resolved through the occurrence supertype chain.

Materials and layer sets are shared; surface styles carry sRGB and transparency.
Presentation layers use the source layer name and uid, assigned to shape
representations. These entities are not IfcRoot and have no GlobalId. Material
associations, void/fill relations and named-storey containment have semantic,
stable GUIDs. Openings use the explicit geometry described in object-record.md.

Current limitations: bare StandardCase/ElementedCase and standalone feature
records requiring material usage, decomposition or host relationships are
reported and skipped. Their names remain available in the vocabulary, but full
specialization export is unfinished. Group registry type references do not emit
an invalid proxy type relationship. Referenced child void geometry is excluded from the host representation;
callers must supply a host already representing the void (no Boolean cut is made). Non-scalar PSD property values need further support.

## Streaming and prototype instancing

Entity lines are written to a buffered ASCII file in increasing id order. The
header precedes DATA and the footer is written last. The stream is closed before
IDS checks open the completed file. Writing no longer retains the complete STEP
text; geometry arrays and the current body's formatting buffers remain in memory.
A failed export can leave a partial file at the requested path.

An export profile may set `"instancing": true` (default `false`) with either
`"geometry": "brep"` or `"geometry": "polygonal"`. Each owned mesh prototype
gets a local-frame shape representation and representation map. Occurrences use
mapped items whose positive uniform scale, rotation and translation come from
the composed world matrix. Element ObjectPlacement remains identity, as in the
baked exporter: the mapping itself takes local prototype coordinates to world
metres. Mirroring, non-uniform scale, shear and singular transforms instead bake
that occurrence's coordinates, using an identity mapping wrapper.

Traversal prunes tagged descendants and opening references before emitting
occurrences. Sharing is at mesh identity, not whole-assembly identity: records
with different excluded descendants cannot accidentally reuse each other's
assembly body. Materials and styles remain occurrence-specific. Face-tagged
subsets and explicit opening bodies retain their existing baked path. Shared
prototype geometry does not imply shared records, element GUIDs or quantities.
