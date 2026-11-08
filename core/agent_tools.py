# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency-free agent schemas and window-scoped extension registrations."""
import json
try:
    from core.ai_recipes import reference
    REFERENCE = reference("llamada")
except ImportError:  # minimal packaged client without the recipe book
    REFERENCE = "IngeTrazo: Z-up, metres. Inspect with query_model."

BUILTIN_TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python against the LIVE IngeTrazo document (Z-up, "
            "metres). Returns stdout/stderr. The reference below is "
            "everything you need — read it instead of exploring the API. "
            "Use query_model/query_groups/query_status for inspection. "
            "Batch related edits; never reset_document_caches after a local "
            "edit. A deferred history command can call "
            "viewport.refresh_after_edit() once after its batch; normal "
            "run_python recipes already refresh automatically.\n\n"
            + REFERENCE),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "query_model",
        "description": ("Model overview: entity counts, group/component "
                        "names, materials, layers, bounds, selection size."),
        "inputSchema": {"type": "object", "properties": {
            "include_bounds": {"type": "boolean", "default": True,
                               "description": "False skips the scene bounds traversal."}}},
    },
    {
        "name": "query_groups",
        "description": ("Read-only nested group metadata with stable uid paths. "
                        "No undo snapshot, geometry baking or redraw. Filter by "
                        "name substring; paginate with next_offset. Pages refer "
                        "to the returned scene version; restart if it changes."),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "default": ""},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}},
    },
    {
        "name": "query_changes",
        "description": ("Read commands since a history revision, including undo/redo. "
                        "complete=false means older entries expired. Tokens are "
                        "per document history, not mesh or scene revisions."),
        "inputSchema": {"type": "object", "properties": {
            "since_revision": {"type": "integer", "minimum": 0, "default": 0}}},
    },
    {
        "name": "query_status",
        "description": ("Read a JSON status variable published in run_python's "
                        "persistent scope. No Python execution, undo snapshot "
                        "or redraw. Missing variables return found=false."),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "screenshot",
        "description": ("Render the current viewport and LOOK at it — use "
                        "after building to verify and iterate."),
        "inputSchema": {
            "type": "object",
            "properties": {"width": {"type": "integer"},
                           "height": {"type": "integer"}},
        },
    },
    {
        "name": "undo",
        "description": "Undo the last step in IngeTrazo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "redo",
        "description": "Redo the last undone step in IngeTrazo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def json_value(value):
    """Reject Python objects and non-finite numbers before committing edits."""
    def check(v, depth=0):
        if depth > 64:
            raise ValueError("agent tool result must be JSON-safe (nesting too deep)")
        if type(v) in (str, int, float, bool, type(None)):
            return
        if type(v) is list:
            for item in v:
                check(item, depth + 1)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for item in v.values():
                check(item, depth + 1)
            return
        raise ValueError("agent tool result must contain only JSON-safe values")
    check(value)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("agent tool result must contain only JSON-safe values") from exc


def extension_registry(window):
    if not hasattr(window, "_agent_tools"):
        window._agent_tools = {}
    return window._agent_tools


def register(registry, name, fn, *, description, input_schema=None, mutates=False):
    if not isinstance(name, str) or not name or not callable(fn):
        raise ValueError("agent tool needs a nonempty name and callable")
    if not isinstance(description, str) or type(mutates) is not bool:
        raise ValueError("description must be a string and mutates a boolean")
    if name in registry:
        raise ValueError(f"agent tool {name!r} is already registered")
    schema = json_value(input_schema if input_schema is not None else
                        {"type": "object", "properties": {}})
    if not isinstance(schema, dict):
        raise ValueError("input_schema must be a JSON Schema object")
    entry = dict(fn=fn, description=description, input_schema=schema, mutates=bool(mutates))
    registry[name] = entry
    def unsubscribe():
        if registry.get(name) is entry:
            del registry[name]
    return unsubscribe


_STRINGS = {"type": "array", "items": {"type": "string"}}
_VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
for _name, _description, _props, _required in [
    ("query_selection", "Inspect selection counts, groups and world bounds.", {}, []),
    ("select", "Select groups by uid or case-sensitive name glob.",
     {"uids": _STRINGS, "names": _STRINGS, "pattern": {"type": "string"},
      "mode": {"enum": ["replace", "add", "remove", "clear"], "default": "replace"}}, []),
    ("query_tree", "Read the outliner in document order; root has depth zero.",
     {"root_uid": {"type": "string"}, "depth": {"type": "integer", "minimum": 0, "default": 2},
      "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
      "include_hidden": {"type": "boolean"}}, []),
    ("query_entity", "Inspect a group, column-major placement matrices and world bounds.", {"uid": {"type": "string"}}, ["uid"]),
    ("query_layers", "Read layers, folder paths and usage counts (shared faces counted once).", {}, []),
    ("set_layer_visibility", "Set layer display visibility through the Layers panel (Previous layer state restores it).", {"uids_or_names": _STRINGS, "visible": {"type": "boolean"}}, ["uids_or_names", "visible"]),
    ("query_camera", "Read the current camera pose and projection.", {}, []),
    ("set_camera", "Set camera pose or a standard view; no document edit.",
     {"preset": {"enum": ["top", "bottom", "front", "back", "right", "left", "iso"]},
      "eye": _VECTOR, "target": _VECTOR, "up": _VECTOR, "ortho": {"type": "boolean"}}, []),
    ("zoom_to", "Frame specified groups, selection, or the whole model.", {"uids": _STRINGS}, []),
]:
    BUILTIN_TOOLS.append(dict(name=_name, description=_description,
        inputSchema=dict(type="object", properties=_props, required=_required)))
next(s for s in BUILTIN_TOOLS if s["name"] == "screenshot")["inputSchema"]["properties"]["uids"] = _STRINGS

# Record commands already own their undo step; mutates advertises this to MCP.
_TEXT = {'type': 'string'}
_PAGE = {'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 200}}
_SCHEMA = {'enum': ['IFC4', 'IFC4X3_ADD2'], 'default': 'IFC4'}
_FORCE = {'type': 'boolean', 'default': False}
for _name, _description, _props, _required in [
    ('query_record', 'Read an object record, resolved type defaults and validation problems.',
     {'uid': _TEXT, 'schema': _SCHEMA}, ['uid']),
    ('query_records', 'Page placed groups in outliner order; totals cover the entire model. Name is a case-insensitive substring. Problems is an error count.',
     {**{k: _TEXT for k in ('class', 'system', 'classification_system', 'code', 'type', 'name')},
      'untagged': {'type': 'boolean'},
      'linked': {'type': 'boolean', 'description': 'true: only groups inside linked files (read-only for this document); false: only this document\'s own groups; omitted: own groups plus tagged linked ones.'},
      'schema': _SCHEMA, **_PAGE}, []),
    ('query_vocabulary', 'Read class templates and registry code counts. Request classification_system or search for paged codes.',
     {'schema': _SCHEMA, 'class': _TEXT, 'classification_system': _TEXT, 'search': _TEXT, **_PAGE}, []),
    ('query_registry', 'Read the detached project registry.', {}, []),
    ('set_record', 'Patch records atomically; nested fields replace. Rejection returns applied=false and per-uid problems. Null removes records.',
     {'uids': _STRINGS, 'patch': {'type': ['object', 'null']}, 'validate_schema': _SCHEMA, 'force': _FORCE}, ['uids', 'patch']),
    ('tag', 'Set a class and optional record name on groups.',
     {'uids': _STRINGS, 'ifc_class': _TEXT, 'name': _TEXT}, ['uids', 'ifc_class']),
    ('untag', 'Remove records in one undo step.', {'uids': _STRINGS}, ['uids']),
    ('add_classification', 'Merge a classification into each record; default name comes from the registry code.',
     {'uids': _STRINGS, 'system': _TEXT, 'code': _TEXT, 'name': _TEXT}, ['uids', 'system', 'code']),
    ('remove_classification', 'Remove one code, or all codes from a namespace, from each record.',
     {'uids': _STRINGS, 'system': _TEXT, 'code': _TEXT}, ['uids', 'system']),
    ('set_registry', 'Replace the project registry after validation.', {'value': {'type': 'object'}}, ['value']),
    ('add_classification_system', 'Upsert a classification namespace and optional codes.',
     {**{k: _TEXT for k in ('key', 'name', 'edition', 'source', 'description')}, 'codes': {'type': 'object'}}, ['key', 'name']),
    ('import_classification_codes', 'Merge CSV code,title[,parent] rows into a namespace atomically.',
     {'system': _TEXT, 'csv_text': _TEXT}, ['system', 'csv_text']),
    *[(name, 'Upsert a project registry entry.', {'key': _TEXT, 'value': {'type': 'object'}}, ['key', 'value'])
      for name in ('set_type', 'set_system')],
    *[(name, 'Delete a registry entry; return referencing uids and refuse unless forced.',
       {'key': _TEXT, 'force': _FORCE}, ['key'])
      for name in ('delete_type', 'delete_system', 'delete_classification_system')],
    ('export_ifc', 'Write the IFC file for a registry export profile (IFC4 default) and return the count, skipped records with reasons, and IDS results. Relative paths land next to the open document.',
     {'path': _TEXT, 'profile': _TEXT, 'project_name': _TEXT}, ['path']),
]:
    BUILTIN_TOOLS.append(dict(name=_name, description=_description,
        mutates=not _name.startswith('query_'),
        inputSchema=dict(type='object', properties=_props, required=_required)))
