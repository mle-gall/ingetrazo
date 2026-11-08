# Object record v1

A placed group owns one JSON object at `group.ifc`. Component instances share
geometry and may reference the same registry type, but own separate records and
GUIDs. Loose-face tags remain the legacy `{id, class, name, guid}` shape; full
records are supported only on groups. Untagged groups have `ifc = null`.

```json
{
  "v": 1,
  "class": "IfcWall",
  "guid": "0YvctVUKr0kugbFTf53O9L",
  "predefined_type": "USERDEFINED",
  "object_type": "Ride enclosure",
  "name": "Queue enclosure",
  "description": "As-built survey",
  "tag": "C-12",
  "classifications": [{"system": "discipline", "code": "A", "name": "Architectural"}],
  "type": "queue_wall",
  "systems": ["ride"],
  "psets": {"Pset_WallCommon": {"Status": {"kind": "enum", "value": "EXISTING"}}},
  "quantities": {"Volume": {"value": 2.5, "source": "manual"}}
}
```

Only `class` is required. Defaults are implicit and need not be serialized.

| Field | JSON value and meaning |
| --- | --- |
| v | Integer 1; absent means 1 |
| guid | Persistent 22-character IFC compressed GUID; assigned once; copies get a new identity |
| class | IFC entity name from `core.ifc_tables` |
| predefined_type | Enum member name or null; absent means null |
| object_type | Text; nonempty when PredefinedType is USERDEFINED |
| name, description, tag | Text, default empty; tag is the element mark |
| classifications | List of system registry key, code, name objects; default empty |
| type | Registry type key or null |
| systems | List of registry system keys; default empty |
| psets | Property set name → property name → typed value; default empty |
| quantities | Quantity name → `{value: number, source: "manual"}`; default empty |

Typed values have `kind` and `value`. Supported kinds are text, label, enum
(string values), boolean, integer, real, length, area and volume (finite numbers).
Lengths, areas and volumes use metres, square metres and cubic metres.
Bare strings, booleans, integers and real numbers normalize to the corresponding
kind; null is not a property value. Measured quantities are computed, never stored.
Status is `Pset_<Class>Common.Status`, with NEW, EXISTING, DEMOLISH, TEMPORARY,
OTHER, NOTKNOWN or UNSET. It is not a top-level field.

Unknown keys, including nested keys, survive persistence unchanged. Normalization
returns a detached view and only expands scalar property shorthand; it does not
materialize defaults or allocate GUIDs. Unsupported schema versions are retained
by persistence but reported by validation.

`core.record.role` derives spatial for Site, Building, BuildingStorey, Space,
SpatialZone, Facility and FacilityPart; assembly for ElementAssembly; part for
BuildingElementPart; otherwise element (all class names have the Ifc prefix).
Role is not serialized. `describe(group)` returns a detached JSON object with
uid, name, record and derived role.

`apply_type(record, registry)` resolves scalar type defaults underneath instance
fields. Psets merge by property name. Instance lists replace type lists. Resolution
never writes inherited data back. This is a resolved view, not a type assignment.

`SetRecordCommand` applies a top-level patch; nested fields replace as units.
Unknown unpatched fields and existing GUIDs survive. A null patch removes the
record. Undo restores the exact prior record; redo reuses its assigned identity.
Metadata changes advance mesh revisions and scene.version, without changing
geometry serials or winding counters. Loose-face changes use SetFaceTagsCommand.

The BIM panel offers object and registry dialogs. The object dialog edits scalar
fields, picks class/PredefinedType/type, and provides classification code and typed
property entry helpers. Classifications have editable rows and removal; systems have membership
checkboxes. Advanced pset and quantity maps are editable JSON. The dialog opens
on the first selected object and its patch carries only the fields the user
changed, so a multi-selection shares the edit while every object keeps its own
name, tag, GUID and unknown fields.

## Schema table scope

The generated schema tables and hand-written common templates contain
interoperability facts, not redistributed EXPRESS or property-set XML. Sources are the buildingSMART lexical documentation for
[IFC4 ADD2 TC1](https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/)
and [IFC4.3 ADD2](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/).
IFC4 is the default. Facility and FacilityPart require IFC4X3_ADD2; these base
classes have no PredefinedType. PredefinedType members are schema-specific and optionally checked against
IfcOpenShell in tests. Common property templates describe IFC4; an empty template
means no correspondingly named common pset exists. Other scalar measures use real
(SI units); logical values use the enum TRUE/FALSE/UNKNOWN. IFC list-valued
BendingParameters is flagged `scalar_only: false`: v1 can retain a textual note
but cannot represent that IFC list without a future typed-value extension.
Exporters must not export that note as an IFC list. IFC4X3-specific pset changes
are outside this IFC4 template catalogue; exporters still need schema validation.

## Materials, voids and storeys

`material` is a material name, or `{"name": "Wall build-up", "layers":
[{"name": "Concrete", "thickness": 0.2}]}`. Thickness is in metres.
Without this field, export chooses a group material or the face material covering
the greatest area. Scene material RGB and opacity supply the surface style.

`openings` is a list of objects with optional `guid`, `name`, and `class`
(default and currently only value: `IfcOpeningElement`). Geometry is either
`faces: [{"outer": [[x,y,z], ...], "holes": [[[x,y,z], ...], ...]}]`,
in world metres, matching issue #1222's attachment, or `group_uid` naming a
child placement. Opening GUIDs are assigned to the stored record once. The
exporter records a void relationship; it does not perform a Boolean subtraction.
A door or window can set `fills` to that opening's compressed GUID.

`storey` is a name. Registry `storeys[name].elevation` supplies its elevation,
otherwise zero. A modelled storey/space ancestor takes precedence; a modelled
building can own the named storey. The attachment's older `{name, elevation}`
form is also accepted, with registry elevation taking precedence. Numeric
quantity shorthand normalizes to `{value: number, source: "manual"}`.
The attachment's free-text `type` remains a registry key: create its registry
entry first; arbitrary type names are not silently turned into definitions.
