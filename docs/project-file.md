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

B2 adds Home, recent files/projects, worksessions and active-file management,
described below.

## Home and worksession (B2)

Starting without a path shows Home. File → Home returns there. Home lists recent
native files and projects, supports pin/unpin, and asks for a replacement path
when an entry has moved. New document retains the units question and its existing
preference. New project creates an empty envelope; save a new document to add its
host entry. The ordinary Open dialog and OS/command-line route accept `.igzproj`.

The optional version-1 project field below is plain JSON. Array order is tab
order; paths are relative to the project directory. Unknown envelope fields are
preserved. Session writes reread the latest envelope before atomic replacement.

```json
"worksession": {
  "files": [
    {"path": "host.igz", "camera": {"target": [0, 0, 0], "distance": 12}},
    {"path": "parts/track.igz", "camera": null}
  ],
  "active_file": "parts/track.igz"
}
```

Camera objects use the existing document camera fields (target, orbit/projection
parameters); absent or null cameras retain the document's view. `active_file`
is null or one of the open paths. Without worksession state, the host-role files
open in file-list order. References remain listed in the browser but cannot
become active modeling documents. Linked sources open in place on one click.
Saving a linked source retains its linked role; the existing watcher refreshes
unpacked placements in all open hosts.

Browser → Worksession selects the editable file. Ordinary tab selection only
changes the viewed file. Non-active tabs are labeled read-only; their model
input, panels, composer and editing menus are disabled and history/agent
mutations are rejected. These are static views: activate a file to navigate or
edit it. Previously made unsaved changes are retained when switching; an explicit
save to that same path can still save those changes. New documents temporarily
become the editable unsaved tab and join the session when saved. Unsaved document
contents are not stored in the project JSON; ordinary save/recovery still applies.
Session state is written on active-file changes, document saves, tab close and
window close. Tab ordering and cameras therefore persist on a normal close.
Already open documents stay in the window and participate in the worksession.

Recent data uses QSettings `home/recent_files` and `home/recent_projects`, each a
JSON array of `{"path": "/absolute/path", "pinned": false}`. Each list is bounded
to 20 entries, pinned first, then most recently opened. The legacy file-menu list
is retained for compatibility. Missing paths stay available in Home for locating.
macOS Dock recent-document registration is not added (no existing one-call bridge).

Visible explicit document saves capture a small PNG as the optional ZIP member
`thumbnail.png` (280 pixels wide). This is additive to the existing IGZ container;
plain old files still load. Headless saves preserve an existing thumbnail and do
not manufacture one. Home bounds thumbnail reads to 1 MiB. Thumbnails are not
geometry or project schema fields and may be omitted when no rendered frame is
available.

Agent tools: `query_worksession()` returns project path, ordered files/roles,
read-only flags and active file; `set_active_file(path)` opens/selects a host or
linked source; `open_project(path)` restores a session; `query_recent()` returns
both recent lists with pin flags. Paths in agent results are absolute.
