# Project registry

The self-contained JSON document lives at `scene.plugin_data["bim_registry"]`.
It has no Python objects or scene pointers. A later project-file implementation
can move this document out of individual IGZ files without changing its keys.
The IfcProject identity remains in `plugin_data.ifc_identity`.

```json
{
  "classification_systems": {
    "discipline": {
      "name": "Discipline", "edition": "", "source": "",
      "description": "ISO 19650 UK / US NCS style discipline codes",
      "codes": {"A": {"name": "Architectural"}, "S": {"name": "Structural"}, "M": {"name": "Mechanical"}}
    },
    "uniclass2015": {"name": "Uniclass 2015", "edition": "2015", "source": "https://uniclass.thenbs.com/", "description": "User-supplied codes"},
    "ride_kinds": {"name": "Ride kinds", "codes": {"SUP": {"name": "Support"}}}
  },
  "types": {
    "queue_wall": {"name": "Queue wall", "ifc_class": "IfcWall", "predefined_type": "STANDARD", "description": "", "psets": {}, "classifications": []}
  },
  "systems": {"ride": {"name": "Ride", "ifc_class": "IfcSystem", "description": ""}},
  "project": {"name": "As-built ride", "description": "", "phase": "As-built", "author": "", "organization": ""},
  "export_profiles": {"handover": {"schema": "IFC4", "view": "ReferenceView", "ids_files": ["requirements.ids"], "description": "Owner handover"}}
}
```

| Section | Key → value |
| --- | --- |
| classification_systems | Namespace key → name, edition, source URI, description, optional codes map |
| codes | Code → name and optional parent code |
| types | Type key → name, ifc_class, predefined_type, object_type, psets, classifications, description |
| systems | System key → name, ifc_class (IfcSystem, IfcDistributionSystem, IfcGroup or IfcZone), description |
| project | name, description, phase, author, organization strings |
| export_profiles | Profile key → schema (IFC4 or IFC4X3_ADD2), view, ids_files list of paths, description |

Keys are stable strings referenced by object records; names are editable labels.
Renaming or deleting a key does not cascade into records. Validate affected
records before exporting. Unknown fields survive edits and persistence.
Profiles are stored and validated here; this phase does not implement their export
behavior. IDS paths are project-relative strings or absolute strings, never opened
by the registry helpers.

`get(scene)` returns a detached view. With no stored registry it returns editable
Discipline and Uniclass metadata seeds. The first panel edit persists that view as
part of the same History transaction. Reads never dirty a document. Existing
registries are not reseeded, so deleting a seed is durable. `seed_defaults`,
`add_system` and `import_codes_csv` return detached documents. All persisted edits
use SetRegistryCommand, including undo/redo. Project and registry edits advance the
scene mesh revision without touching coordinates.

CSV import accepts UTF-8 text with `code,title[,parent]` headers, quoted commas and
an optional BOM. It merges codes, replacing matching existing codes, and rejects
empty code/title or duplicate codes within the import. Failure leaves the source
registry untouched. Parent strings are preserved; external or incomplete
hierarchies are allowed. No Uniclass code tables are bundled: users must supply
licensed data. The registry dialog includes namespace creation and CSV import;
its JSON editor exposes all sections, including types and systems.
