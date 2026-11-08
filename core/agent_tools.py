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
