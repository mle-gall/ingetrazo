# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Linked files: another .igz placed in this one as a live reference.

A linked file is a component whose definition is not the host's: it is the
source document, loaded from disk. The source stays a document of its own —
open it, edit it, save it, and every host that links it shows the change
(the window watches the files, :mod:`views.link_watcher`). Inside the host
the linked part moves, turns and scales like any component, but it cannot
be opened for editing there: entering it offers to open the source.

What is stored where
--------------------
* Each placed copy carries ``Group.ext["link"] = {"path": …}`` — the source,
  absolute — and ``"rel"``, the same path relative to the host when it was
  last saved, tried first so a project folder can move as a whole.
* The host's ``plugin_data["links"]`` keeps, per source, the tag overrides
  (below) and whether the source is *packed*.
* Unpacked (the default), the host file does not hold the source's
  geometry: the copies are saved as empty placements and filled in again
  from the source when the host is opened (:func:`resolve`). Packed —
  Blender's «Pack external data» — the geometry is saved in the host like
  any component's and the source is no longer read; unpacking links it
  again.

Tags
----
The source's tags come into the host under their own names prefixed by the
file's («Site / Wood»), so they never mix with the host's tags of the same
name, in a folder named after the file inside «Linked files», where the
source's own folders are rebuilt. Each tag shows as the source has it,
unless it was switched in the host: that switch is an *override*, kept by
the host and never written to the source, and the source's later changes to
that tag no longer reach it. Overrides are cleared per file
(:func:`clear_overrides`).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

LINK_KEY = "link"                 # Group.ext key on each placed copy
REGISTRY_KEY = "links"            # scene.plugin_data key
LINKED_FOLDER = "Linked files"    # the tag folder all links' folders sit in
SEP = " / "                       # between the file's name and a tag's

_loading = threading.local()      # the sources being loaded (cycle guard)


# ---- what is linked ----------------------------------------------------------

def link_of(group) -> dict | None:
    ext = getattr(group, "ext", None)
    link = ext.get(LINK_KEY) if isinstance(ext, dict) else None
    return link if isinstance(link, dict) and link.get("path") else None


def is_linked(group) -> bool:
    return link_of(group) is not None


def linked_ancestor(group):
    """``group`` or the first group above it that is a linked copy."""
    g = group
    while g is not None:
        if is_linked(g):
            return g
        g = getattr(g, "owner", None)
    return None


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def linked_groups(scene, path=None) -> list:
    """Every linked copy in the document (at any depth), or only the copies
    of ``path``."""
    from core.purge import iter_groups
    want = _norm(path) if path is not None else None
    out = []
    for g in iter_groups(getattr(scene, "groups", None) or ()):
        link = link_of(g)
        if link and (want is None or _norm(link["path"]) == want):
            out.append(g)
    return out


def sources(scene) -> list:
    """The linked source files, each once, in first-placed order."""
    seen, out = set(), []
    for g in linked_groups(scene):
        p = _norm(link_of(g)["path"])
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def registry(scene) -> dict:
    data = getattr(scene, "plugin_data", None)
    if not isinstance(data, dict):
        data = scene.plugin_data = {}
    reg = data.get(REGISTRY_KEY)
    if not isinstance(reg, dict):
        reg = data[REGISTRY_KEY] = {}
    return reg


def _entry(scene, path) -> dict:
    reg = registry(scene)
    key = _norm(path)
    entry = reg.get(key)
    if not isinstance(entry, dict):
        entry = reg[key] = {}
    entry.setdefault("overrides", {})
    return entry


def is_packed(scene, path) -> bool:
    return bool(registry(scene).get(_norm(path), {}).get("packed"))


def stem(path) -> str:
    return Path(path).stem


def tag_name(path, tag: str) -> str:
    """The host's name for the source's tag ``tag``."""
    from core.layers import DEFAULT_LAYER
    return stem(path) + SEP + ("Untagged" if tag in (None, "", DEFAULT_LAYER)
                               else tag)


def link_tags(scene, path) -> list:
    """The host tags that stand for ``path``'s tags."""
    prefix = stem(path) + SEP
    return [ly.name for ly in scene.layers if ly.name.startswith(prefix)
            and ly.name in _entry(scene, path).get("tags", ())]


def source_of_tag(scene, name: str):
    """The source file a host tag belongs to, or None for the host's own."""
    for key, entry in registry(scene).items():
        if isinstance(entry, dict) and name in (entry.get("tags") or ()):
            return key
    return None


# ---- loading a source -----------------------------------------------------------

class LinkError(Exception):
    """A source that cannot be linked: missing, unreadable, or a cycle."""


def locate(link: dict, host_path=None) -> Path | None:
    """Where the source is: next to the host as last saved (``rel``), then
    the absolute path. None when neither exists."""
    rel = link.get("rel")
    if rel and host_path is not None:
        cand = (Path(host_path).parent / rel)
        if cand.is_file():
            return cand.resolve()
    p = Path(link["path"])
    return p if p.is_file() else None


def load_source(path, select=None):
    """``(definition, source scene)`` for the .igz at ``path``: the whole
    document as one component definition (``core.insert``), its own links
    resolved first. Raises :class:`LinkError`."""
    from core.scene import Scene
    from formats import igz
    key = _norm(path)
    stack = getattr(_loading, "stack", None)
    if stack is None:
        stack = _loading.stack = []
    if key in stack:
        raise LinkError(f"{Path(path).name} links itself (through "
                        f"{' → '.join(Path(p).name for p in stack)})")
    if not Path(path).is_file():
        raise LinkError(f"{path} was not found")
    stack.append(key)
    try:
        src = Scene()
        igz.load_into(src, Path(path))
        # A cycle further down is this link's failure too; a source of the
        # source that is merely missing is not (its copies show empty).
        for err in (getattr(src, "link_errors", None) or {}).values():
            if "links itself" in err:
                raise LinkError(err)
        # The source's tag table outlives the component (which consumes the
        # scene's meshes, not its tags).
        tags = {"layers": [ly.to_dict() for ly in src.layers],
                "folders": list(getattr(src, "layer_folders", ()) or ()),
                "parents": dict(getattr(src, "folder_parents", {}) or {})}
        materials = dict(getattr(src, "materials", {}) or {})
        from core.group import Group
        from core.insert import is_scale_figure
        from core.mesh import Mesh
        from PySide6.QtGui import QMatrix4x4
        validate_select(select)
        groups = [g for g in src.groups if not is_scale_figure(g)]
        mesh = src.mesh
        if select is not None:
            from core.facets import build, evaluate
            wanted = set(select['uids']) if 'uids' in select else set(evaluate(build(src), select['filter']))
            selected = []
            def visit(items, parent):
                for group in items:
                    world = parent * (group.xform or QMatrix4x4())
                    if group.uid in wanted:
                        group.xform = world
                        selected.append(group)
                    else:
                        visit(group.children or (), world)
            visit(groups, QMatrix4x4())
            groups, mesh = selected, Mesh()
        comp = Group(mesh, name=stem(path))
        comp.adopt(groups)
    except LinkError:
        raise
    except Exception as exc:  # noqa: BLE001 — any reader failure
        raise LinkError(f"{Path(path).name}: {exc}") from exc
    finally:
        stack.remove(key)
    if comp is None:
        from core.group import Group
        comp = Group(name=stem(path))
    if comp.xform is None:
        from PySide6.QtGui import QMatrix4x4
        comp.xform = QMatrix4x4()
    comp.component = True
    return comp, tags, materials


def _relabel_deferred(mesh, rename) -> bool:
    """Relabel a mesh the document left deferred (``core.mesh.DeferredMesh``)
    in its tables — the face-attribute rows and the edge tag names —
    without building it: touching ``mesh.faces`` would build all of them,
    and the 1.6 M faces of Maxence's facilities model took 46 s to link that
    way (2026-11-07). The tables are replaced, never edited in place (other
    meshes may share them), and what was derived from them is dropped: the
    lazy plan, and the drawing cache's key and bake (the key hashes the
    tables, so the bake is rebuilt, never shown stale). False for a mesh
    that is already built."""
    from core.mesh import DeferredMesh
    if type(mesh) is not DeferredMesh:
        return False
    import numpy as np
    d = mesh.__dict__
    src = dict(d["_deferred_source"])
    meta = dict(src.get("meta") or {})
    untagged = rename(None)
    # Faces: each row of the attribute table, and a row for the faces that
    # had none (they were on the default tag).
    table = [dict(row) for row in (meta.get("face_attrs") or [])]
    for row in table:
        row["layer"] = rename(row.get("layer"))
    nfaces = len(src.get("counts") if src.get("counts") is not None else ())
    fa = src.get("face_attr")
    fa = (np.full(nfaces, -1, dtype=np.int32) if fa is None
          else np.array(fa, copy=True))
    if fa.size and (fa < 0).any():
        table.append({"layer": untagged})
        fa[fa < 0] = len(table) - 1
    src["face_attr"] = fa
    meta["face_attrs"] = table
    # Edges: the name table, and a name for the untagged ones.
    names = [rename(n) for n in (meta.get("edge_layers") or [])]
    nedges = len(src["edges"]) if src.get("edges") is not None else 0
    lay = src.get("layers")
    lay = (np.full(nedges, -1, dtype=np.int32) if lay is None
           else np.array(lay, copy=True))
    if lay.size and (lay < 0).any():
        names.append(untagged)
        lay[lay < 0] = len(names) - 1
    src["layers"] = lay
    meta["edge_layers"] = names
    src["meta"] = meta
    d["_deferred_source"] = src
    for key in ("_deferred_plan", "_drawing_staged", "_drawing_source_key"):
        d.pop(key, None)
    # The build the loader left reads its own copy of the original tables;
    # if the mesh is ever built (an edit, a pick into it), its faces and
    # edges are relabelled right after — the drawing, from the tables
    # above, already shows the new names.
    original = d["_deferred"]

    def build(m, original=original, rename=rename):
        from core.layers import assign_layer, layer_of
        original(m)
        for f in m.faces:
            assign_layer(f, rename(layer_of(f)))
        for e in m.edges:
            assign_layer(e, rename(layer_of(e)))
    d["_deferred"] = build
    return True


def _rename_tags(comp, path) -> None:
    """Move the definition's geometry onto the host's names for the
    source's tags (:func:`tag_name`)."""
    from core.group import iter_placements
    from core.layers import assign_layer, layer_of

    def rename(name):
        return tag_name(path, name)
    seen = set()
    for g, _m in iter_placements(comp):
        if g is not comp:
            assign_layer(g, tag_name(path, layer_of(g)))
        if id(g.mesh) in seen:
            continue
        seen.add(id(g.mesh))
        if _relabel_deferred(g.mesh, rename):
            continue
        for f in g.mesh.faces:
            assign_layer(f, tag_name(path, layer_of(f)))
        for e in g.mesh.edges:
            assign_layer(e, tag_name(path, layer_of(e)))


def _apply_tags(scene, path, tags) -> None:
    """Bring the source's tags into the host (see the module notes): the
    folder of the file inside «Linked files», the source's folders below
    it, each tag as the source shows it unless overridden here. Tags of
    this file the source no longer has are dropped when nothing uses
    them."""
    from core.layers import Layer, folders_of, move_folder
    entry = _entry(scene, path)
    overrides = entry["overrides"]
    # What the source said last time: a tag the host now shows otherwise
    # was switched here — by the Tags panel, Isolate, a saved view, any
    # road — and that switch is the host's override from now on.
    last = entry.setdefault("source_visible", {})

    def folder(name, parent):
        if name not in folders_of(scene):
            scene.layer_folders = folders_of(scene) + [name]
        move_folder(scene, name, parent)
        return name

    top = folder(LINKED_FOLDER, None)
    own = folder(stem(path), top)
    src_folders = {}
    for f in tags.get("folders") or ():
        src_folders[f] = stem(path) + SEP + f
    for f in tags.get("folders") or ():
        parent = tags.get("parents", {}).get(f)
        folder(src_folders[f], src_folders.get(parent, own))

    wanted = []
    for raw in tags.get("layers") or ():
        src = Layer.from_dict(raw)
        name = tag_name(path, src.name)
        wanted.append(name)
        ly = scene.layer(name)
        if ly is None:
            ly = Layer(name)
            scene.layers.append(ly)
        elif name in last and name not in overrides \
                and bool(ly.visible) != bool(last[name]):
            overrides[name] = bool(ly.visible)
        last[name] = bool(src.visible)
        ly.color = src.color
        ly.linetype = src.linetype
        ly.lineweight = src.lineweight
        ly.opacity = src.opacity
        ly.folder = src_folders.get(src.folder, own)
        ly.visible = overrides.get(name, src.visible)
    old = set(entry.get("tags") or ()) - set(wanted)
    entry["tags"] = wanted
    if old:
        used = _used_tags(scene)
        scene.layers[:] = [ly for ly in scene.layers
                           if ly.name not in old or ly.name in used]
        for name in old:
            overrides.pop(name, None)
            last.pop(name, None)


def _used_tags(scene) -> set:
    from core.purge import layer_carriers
    from core.layers import layer_of
    return {layer_of(e) for e in layer_carriers(scene)}


def _install(scene, path, comp) -> None:
    """Every copy of ``path`` shows ``comp``: they share its prototype
    mesh and nested placements, each keeping its own transform, tag,
    paint and name."""
    for g in linked_groups(scene, path):
        _populate(g, comp)
    _entry(scene, path)['loaded_mtime_ns'] = Path(path).stat().st_mtime_ns
    scene.version += 1


def validate_select(select):
    """Only source UIDs or a Navigator expression can define a subset."""
    if select is None:
        return
    if not isinstance(select, dict) or set(select) not in ({'uids'}, {'filter'}):
        raise ValueError('select requires exactly uids or filter')
    if 'uids' in select:
        if not isinstance(select['uids'], list) or any(not isinstance(u, str) for u in select['uids']):
            raise ValueError('uids must be a list of strings')
    else:
        from core.facets import validate_filter
        validate_filter(select['filter'])


def stable_uid(placement_uid, source_uid):
    """Versioned, platform-independent UUID5 mapping; paths never participate."""
    import uuid
    return uuid.uuid5(uuid.NAMESPACE_URL, 'ingetrazo:link:v1:' + placement_uid + ':' + source_uid).hex[:16]


def _populate(placement, source):
    from copy import copy, deepcopy
    from PySide6.QtGui import QMatrix4x4
    def clone(group, parent):
        result = copy(group)
        result.uid = stable_uid(placement.uid, group.uid)
        result.ext = deepcopy(group.ext)
        result.ifc = deepcopy(group.ifc)
        if result.ifc:
            for opening in result.ifc.get('openings', []):
                if opening.get('group_uid'):
                    opening['group_uid'] = stable_uid(placement.uid, opening['group_uid'])
        result.xform = QMatrix4x4(group.xform) if group.xform is not None else None
        result.owner = parent
        result.children = [clone(c, result) for c in group.children or ()]
        return result
    placement.mesh = source.mesh
    placement.children = [clone(c, placement) for c in source.children or ()]
    placement.component = True


# ---- the entry points --------------------------------------------------------------

def make_link(scene, path, host_path=None, select=None):
    """A copy of the .igz at ``path`` ready to place in ``scene`` (by the
    placement tool, like an imported component), its tags brought in.
    Raises :class:`LinkError`."""
    path = Path(path).resolve()
    if host_path is not None and _norm(path) == _norm(host_path):
        raise LinkError("a document cannot link itself")
    comp, tags, materials = load_source(path, select)
    _rename_tags(comp, path)
    _merge_materials(scene, materials, comp)
    _apply_tags(scene, path, tags)
    comp.ext = {LINK_KEY: _link_record(path, host_path)}
    if select is not None:
        from copy import deepcopy
        comp.ext[LINK_KEY]['select'] = deepcopy(select)
    _populate(comp, comp)
    _entry(scene, path)['loaded_mtime_ns'] = path.stat().st_mtime_ns
    comp.name = stem(path)
    return comp


def _link_record(path, host_path) -> dict:
    rec = {"path": str(Path(path).resolve())}
    if host_path is not None:
        try:
            rec["rel"] = os.path.relpath(Path(path).resolve(),
                                         Path(host_path).resolve().parent)
        except ValueError:          # another drive (Windows)
            pass
    return rec


def _merge_materials(scene, materials, comp) -> None:
    if materials:
        from core.insert import merge_materials
        merge_materials(materials, scene.materials, comp)


def reload(scene, path, host_path=None) -> None:
    """Read ``path`` again and show it in every copy. Raises
    :class:`LinkError` (the copies keep what they showed)."""
    # Prepare every subset before changing any placement.
    prepared = []
    for group in linked_groups(scene, path):
        comp, tags, materials = load_source(path, link_of(group).get('select'))
        _rename_tags(comp, path)
        _merge_materials(scene, materials, comp)
        prepared.append((group, comp, tags))
    for group, comp, tags in prepared:
        _apply_tags(scene, path, tags)
        _populate(group, comp)
    _entry(scene, path)['loaded_mtime_ns'] = Path(path).stat().st_mtime_ns
    scene.version += 1


def resolve(scene, host_path=None) -> dict:
    """Fill the linked copies of a document just opened from their sources
    (packed ones keep what the file holds). Returns ``{path: error}`` for
    the sources that could not be read — their copies stay empty
    placements, kept, so a later save does not lose the link."""
    errors: dict = {}
    stack = getattr(_loading, "stack", None)
    if stack is None:
        stack = _loading.stack = []
    host_key = _norm(host_path) if host_path is not None else None
    if host_key is not None and host_key not in stack:
        # The document being opened is part of the chain: a source that
        # links back to it is a cycle.
        stack.append(host_key)
        try:
            return resolve(scene, host_path)
        finally:
            stack.remove(host_key)
    for g in linked_groups(scene):
        link = link_of(g)
        found = locate(link, host_path)
        if found is not None and _norm(found) != _norm(link["path"]):
            link["path"] = str(found)     # the project moved: follow it
    for path in sources(scene):
        if is_packed(scene, path):
            continue
        try:
            reload(scene, path, host_path)
        except LinkError as exc:
            errors[path] = str(exc)
    scene.link_errors = errors
    return errors


def set_packed(scene, path, packed: bool) -> None:
    """Pack (the host file keeps the geometry) or unpack (it is read from
    the source again — reloaded now)."""
    _entry(scene, path)["packed"] = bool(packed)


def note_visibility(scene, name: str, visible: bool) -> bool:
    """The host switched tag ``name``: if it is a linked file's, remember
    it as an override. Returns True when it was."""
    path = source_of_tag(scene, name)
    if path is None:
        return False
    _entry(scene, path)["overrides"][name] = bool(visible)
    return True


def clear_overrides(scene, path, host_path=None) -> None:
    """Show ``path``'s tags as the source has them again."""
    entry = _entry(scene, path)
    entry["overrides"] = {}
    # Back to what the source said, so the reload does not read the old
    # override as a new one.
    for name, vis in (entry.get("source_visible") or {}).items():
        ly = scene.layer(name)
        if ly is not None:
            ly.visible = bool(vis)
    reload(scene, path, host_path)


def refresh_paths(scene, host_path) -> None:
    """Rewrite each link's ``rel`` for the host's new location (Save As)."""
    for g in linked_groups(scene):
        g.ext[LINK_KEY].update(_link_record(link_of(g)["path"], host_path))


def save_as_placeholder(group, scene) -> bool:
    """Whether the .igz writer saves ``group`` as an empty placement (an
    unpacked link: the source holds the geometry)."""
    link = link_of(group)
    return link is not None and not is_packed(scene, link["path"])


def query(scene):
    """JSON metadata for UI and agents, without touching geometry."""
    from core.group import iter_placements
    rows = []
    for group in linked_groups(scene):
        rec = link_of(group)
        path = Path(rec['path'])
        stamp = path.stat().st_mtime_ns if path.is_file() else None
        state = ('packed' if is_packed(scene, path) else 'missing' if stamp is None
                 else 'modified' if stamp != _entry(scene, path).get('loaded_mtime_ns')
                 else 'resolved')
        rows.append(dict(uid=group.uid, path=str(path), status=state,
                         select=rec.get('select'), stable_uid_count=sum(1 for _ in iter_placements(group)) - 1))
    return rows
