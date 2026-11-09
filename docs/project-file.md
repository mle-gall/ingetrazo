# Shared projects and linked placements (version 1)

An .igzproj is UTF-8 plain JSON, with no executable or Python-specific data.
Unknown fields are preserved. All measurements remain in metres.

    {
      "version": 1,
      "bim_registry": {},
      "ifc_identity": {
        "namespace": "ca2c12df23ac48f9a103455660d950e5",
        "project": "2gB0vM6Bf8mPFPXX3tF4sX",
        "site": "2gB0vM6Bf8mPFPXX3tF4sY",
        "building": "2gB0vM6Bf8mPFPXX3tF4sZ",
        "storey": "2gB0vM6Bf8mPFPXX3tF4sa"
      },
      "files": [
        {"path": "host.igz", "role": "host"},
        {"path": "parts/track.igz", "role": "linked"},
        {"path": "survey.pdf", "role": "reference"}
      ],
      "links": [
        {"host": "host.igz", "source": "parts/track.igz",
         "placement_uid": "0123456789abcdef", "select": {"uids": ["fedcba9876543210"]}}
      ]
    }

The bim_registry object is the entire document described in project-registry.md,
including classification systems, types, systems, project metadata, export profiles,
tag sets, storeys, pset library, views and rules. Namespace is a UUID hexadecimal
string; spatial identities are compressed IFC GUIDs. Creation retains existing
document identities and fills missing identities using UUID5 as the IFC exporter
does. Every attached host exports the project's IfcProject identity.

File and graph paths are relative to the project directory (including ..
when required). Roles are host, linked, reference; saving a host updates
its outgoing graph and file entries without discarding other hosts or references.
Registry resource paths retain the registry's existing path semantics.

Each IGZ stores plugin_data.project = {"path": "/absolute/project.igzproj",
"rel": "../project.igzproj"}. The existing relative path is tried first; the
absolute path is the fallback. Save As refreshes rel. Moving a whole project
folder preserves its relationships. A missing project uses the local registry;
editing an attached registry with a missing project fails rather than recreating
a shared file silently.

Browser → Links → “Move registry to project…” copies the current whole registry
and IFC identity to the selected project file and attaches the document.
The local registry remains a fallback and migration source.
set_project(path) attaches another host to an existing project.

Registry reads refresh from disk. SetRegistryCommand, undo and redo write the
shared file using atomic replacement. A changed nanosecond mtime since the
document's last read/write produces a RuntimeWarning and scene.project_warning.
The entire registry of the last writer wins; this is not a merge or a lock.
Undo is also a shared write and can replace a later author's registry.
Atomic replacement prevents partial JSON reads but does not serialize competing
writers. The local registry fallback is updated after successful writes.

## Link selection and identity

A placement stores ext.link = {"path": "...", "rel": "...", "select": ...}.
Absent or null select links the full document. Exactly one selector is allowed:

* {"uids": ["source-group-uid", "..."]}
* {"filter": {"facet": "name", "glob": "Track*"}}

Filters use the Navigator grammar (facet with eq/in/glob/exists/gt/lt, text,
all/any/not). They run against source metadata before host tag renaming.
Selecting a parent includes its subtree. Selecting a child applies all ancestor
transforms to its new root transform. Selecting both includes it once.
Unmatched UIDs instantiate nothing; a rename preserves a UID selection.
The source is read to evaluate selections, but only matching subtrees are
instantiated in the host. Loose geometry is included only in full links.

For every source group, the host UID is the first 16 lowercase hex characters of
UUID5 using the standard URL namespace and this UTF-8 name:
ingetrazo:link:v1:<placement uid>:<source group uid>.
Names and filesystem paths do not participate. A separate wrapper retains the
link placement UID and transform; source groups, including a sole source root,
are its children. Two hosts sharing the placement UID get identical child UIDs;
separate placements differ. Linked records remain read-only. Opening group UID
references are mapped to the same namespace.

Older hosts need no rewrite: resolving their placeholders assigns stable UIDs
on the next load. Old transient linked UIDs in views or external references
cannot be recovered automatically. Packed geometry keeps its stored UIDs until
unpacked/reloaded. Source files lacking persistent group UIDs must first be
saved in the current IGZ format to establish identities.

The Links tab exposes status, subset, stable UID count, reload, relink, open,
pack/unpack, source-selection linking and subset JSON editing. “Link selection…”
uses selected groups from another open document's saved file; save source edits
before linking. Agents expose query_links, link_document(path, select),
reload_link(path), query_project and set_project(path).

B2 remains the Home/start window with recent files and projects, plus worksession
and active-file management.
