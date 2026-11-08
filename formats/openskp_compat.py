# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Import bridges for OpenSKP 1.5: layers, folders, kinds and entity IDs.

Dimension paths and anchored annotation reading are upstream now (#384,
#473, #484); their local replacements have been removed. The definition-list
end fix still applies, but must preserve 1.5's inline-entity bookkeeping.
The 2019 layer-tail check must not mistake an unrelated version check for
support of the extra two bytes.
"""
from __future__ import annotations

import struct
import threading

_applied = False
_parse_tables = threading.local()   # the last parse's layer id → name


def apply() -> bool:
    """Install the fixes into ``openskp`` when needed. Returns True when a
    patch was installed (idempotent)."""
    global _applied
    if _applied:
        return False
    try:
        from openskp import legacy as L
    except Exception:  # noqa: BLE001 — no openskp: nothing to fix
        return False
    _applied = True
    _keep_legacy_pids(L)
    layers = _keep_layer_table()
    folders = _keep_tag_folders()
    lists = _fix_definition_list_end(L)
    groups = _note_legacy_groups(L)
    kinds = _note_definition_kinds()
    tails = _fix_layer_tail_2019(L)
    return layers or lists or groups or kinds or tails or folders


def _keep_legacy_pids(L):
    """Carry 2017+ entity IDs through the two places upstream drops them."""
    preamble, reader, fill = L._preamble, L._read_instance, L._fill_builder
    if getattr(reader, "_keeps_pid", False):
        return

    def read_preamble(ar, r):
        start = r.pos
        result = preamble(ar, r)
        for frame in getattr(_parse_tables, "pid_frames", ()):
            if frame[:2] == (id(r), start):
                frame[2]["pid"] = result.get("pid")
        return result

    def read_instance(ar, r):
        frames = getattr(_parse_tables, "pid_frames", None)
        if frames is None:
            frames = _parse_tables.pid_frames = []
        captured = {}
        frames.append((id(r), r.pos, captured))
        try:
            result = reader(ar, r)
            result["persistent_id"] = captured.get("pid")
            return result
        finally:
            frames.pop()

    def fill_builder(builder, ents, slots):
        start = len(builder.instances)
        result = fill(builder, ents, slots)
        records = [v for _, _, v in ents
                   if isinstance(v, dict) and v.get("k") in ("instance", "image")]
        for instance, record in zip(builder.instances[start:], records):
            instance["persistent_id"] = record.get("persistent_id")
        return result

    read_instance._keeps_pid = True
    L._preamble = read_preamble
    L._read_instance = read_instance
    L._READERS["CGroup"] = L._READERS["CComponentInstance"] = read_instance
    L._fill_builder = fill_builder


def _note_legacy_groups(L) -> bool:
    """Remember which definitions a classic (pre-2021) file places through a
    ``CGroup`` — a GROUP — rather than a ``CComponentInstance``.
    The reader reads both the same way and the model it builds keeps no
    trace of which it was, so a group arrived as a component. The ids land
    in a per-thread set, reset before each parse (see
    :func:`reset_group_definitions`)."""
    readers = getattr(L, "_READERS", None)
    original = (readers or {}).get("CGroup")
    if original is None or getattr(original, "_notes_groups", False):
        return False

    def read_group(ar, r):
        rec = original(ar, r)
        if isinstance(rec, dict) and rec.get("def") is not None:
            if not hasattr(_parse_tables, "groups"):
                _parse_tables.groups = set()
            _parse_tables.groups.add(rec["def"])
        return rec

    read_group._notes_groups = True
    readers["CGroup"] = read_group
    return True


def _note_definition_kinds() -> bool:
    """Remember which definitions a 2021+ file marks as GROUPS (#1029). The
    definition record carries its kind in ``8315``: 0 a component, 1 a
    group, 2 the quad behind an Image — the reader only keeps "image". It
    hands each definition's records to ``_extract_geometry_from_nodes``
    once, so that is where the kind is read; the root and the nested calls
    carry no ``8315`` and pass straight through."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    original = getattr(_core, "_extract_geometry_from_nodes", None)
    if original is None or getattr(original, "_notes_kinds", False) \
            or not hasattr(_core, "extract_entity_id"):
        return False

    def _extract_geometry_from_nodes(elements, builder):
        for el in elements:
            if (el.get("tag") if isinstance(el, dict) else el.tag) == "8315":
                pay = el["payload"] if isinstance(el, dict) else el.payload
                kind = _core.parse_var_int(pay, 0, len(pay))
                from types import SimpleNamespace
                did = (_core.extract_entity_id({"children": elements})
                       if isinstance(el, dict) else
                       _core._entity_id(SimpleNamespace(children=elements)))
                if did is not None:
                    _parse_tables.kinds = True
                    if kind == 1:
                        if not hasattr(_parse_tables, "groups"):
                            _parse_tables.groups = set()
                        _parse_tables.groups.add(did)
                break
        return original(elements, builder)

    _extract_geometry_from_nodes._notes_kinds = True
    _core._extract_geometry_from_nodes = _extract_geometry_from_nodes
    return True


def group_definitions() -> set:
    """The definition ids the last parse on this thread placed as GROUPS:
    through a ``CGroup`` in a classic file, by the definition's own kind in
    a 2021+ one."""
    return set(getattr(_parse_tables, "groups", None) or ())


def kinds_known(legacy: bool) -> bool:
    """Whether the last parse told groups from components: for a classic
    file when its group records are being noted (its instance records say
    which), for a 2021+ one when its definitions carried their kind."""
    if legacy:
        try:
            from openskp import legacy as L
        except Exception:  # noqa: BLE001
            return False
        reader = (getattr(L, "_READERS", None) or {}).get("CGroup")
        return bool(getattr(reader, "_notes_groups", False))
    return bool(getattr(_parse_tables, "kinds", False))


def reset_group_definitions() -> None:
    """Forget the groups of the previous parse — call before parsing."""
    _parse_tables.groups = set()
    _parse_tables.kinds = False


def _keep_layer_table() -> bool:
    """Wrap ``openskp._core.full_parse`` so the layer id → name table it
    builds outlives the parse (both eras go through it)."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    original = getattr(_core, "full_parse", None)
    if original is None or getattr(original, "_keeps_layers", False):
        return False

    def full_parse(*args, **kwargs):
        parsed = original(*args, **kwargs)
        table = (parsed.get("layer_id_to_name")
                 if isinstance(parsed, dict) else None)
        _parse_tables.layers = dict(table or {})
        # Instance dataclasses discard the retained entity-info subtree.
        from types import SimpleNamespace
        _parse_tables.pids = {}
        for key, definition in parsed.get("defs_dict", {}).items():
            instances = definition["builder"].instances
            _parse_tables.pids[key] = [
                i.get("persistent_id") or
                _core._entity_id(SimpleNamespace(children=i.get("children", [])))
                for i in instances]

        return parsed

    full_parse._keeps_layers = True
    _core.full_parse = full_parse
    return True


# ---- tag folders (SketchUp 2021+) ----------------------------------------
# openskp reads the tag list (993A) but not its sibling, the folder manager
# (9B3A), so folders never reached IngeTrazo. Decoded from Maxence's
# production files (2026-11-07), whose Tags panel nests them three deep:
#
#   9B3A  folder manager — one root folder, unnamed
#     803E  folder: DC05 its id (the tags' id format), 813E its name
#           (UTF-8), 833E its subfolders (803E records), 843E the ids of
#           the tags in it (each: one length byte, then the var-int),
#           823E hidden (one byte: 1 = hidden), 853E a flag left unread.
#
# A tag's own record (8C3C) does not name its folder (its 903C reads 0
# throughout): membership is the folder's list.

#: Folder records' children, by tag.
_F_FOLDER, _F_NAME, _F_SUBS, _F_TAGS, _F_HIDDEN = (
    "803E", "813E", "833E", "843E", "823E")


def _records(data: bytes, start: int = 0, end: int | None = None):
    """``(tag, payload)`` for each TLV record in ``data[start:end]``: a
    two-byte tag (written as openskp spells it, e.g. ``'803E'``) and a
    little-endian u32 length."""
    end = len(data) if end is None else end
    i = start
    while i + 6 <= end:
        tag = data[i:i + 2].hex().upper()
        n = struct.unpack_from("<I", data, i + 2)[0]
        if i + 6 + n > end:
            return
        yield tag, data[i + 6:i + 6 + n]
        i += 6 + n


def _id_list(payload: bytes) -> list:
    """843E: tag ids, each a length byte then a var-int."""
    from openskp._core import parse_var_int
    out, i = [], 0
    while i < len(payload):
        n = payload[i]
        if n == 0 or i + 1 + n > len(payload):
            break
        out.append(parse_var_int(payload, i + 1, n))
        i += 1 + n
    return out


def _entity_key(payload: bytes):
    from openskp._core import parse_var_int, read_u32
    if payload.startswith(bytes([0xDE, 0x05])):
        return parse_var_int(payload, 6, read_u32(payload, 2))
    return parse_var_int(payload, 0, len(payload))


def parse_tag_folders(payload: bytes) -> list:
    """The folders a 9B3A payload holds, depth first, as dicts
    ``{"key", "name", "parent", "hidden", "tags"}`` — ``parent`` the key of
    the enclosing folder (None at the top), ``tags`` the tag ids filed
    directly in it. The unnamed root is not one of them."""
    out: list = []

    def folder(body: bytes, parent, is_root: bool) -> None:
        rec = {"key": None, "name": "", "parent": parent, "hidden": False,
               "tags": []}
        subs = []
        for tag, pay in _records(body):
            if tag == "DC05":
                try:
                    rec["key"] = _entity_key(pay)
                except Exception:  # noqa: BLE001
                    pass
            elif tag == _F_NAME:
                rec["name"] = pay.decode("utf-8", errors="replace")
            elif tag == _F_SUBS:
                subs = [p for t, p in _records(pay) if t == _F_FOLDER]
            elif tag == _F_TAGS:
                rec["tags"] = _id_list(pay)
            elif tag == _F_HIDDEN:
                rec["hidden"] = bool(pay[:1] == b"\x01")
        me = None
        if not is_root:
            if rec["key"] is None:
                rec["key"] = ("anon", len(out))
            out.append(rec)
            me = rec["key"]
        for sub in subs:
            folder(sub, me, False)

    for tag, pay in _records(payload):
        if tag == _F_FOLDER:
            folder(pay, None, True)
    return out


def _find_node(node, tag):
    if node.tag == tag:
        return node
    for kid in getattr(node, "children", None) or ():
        hit = _find_node(kid, tag)
        if hit is not None:
            return hit
    return None


def _keep_tag_folders() -> bool:
    """Watch the parse go by for the folder manager: openskp hands it over
    as an opaque record inside the model's ``F801`` section (with the tag
    list), so the folders are decoded here and kept for the importer
    (:func:`tag_folder_records`)."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    iterate = getattr(_core, "iter_top_level_lazy", None)
    parse = getattr(_core, "full_parse", None)
    if iterate is None or parse is None \
            or getattr(iterate, "_keeps_folders", False):
        return False

    def iter_top_level_lazy(*args, **kwargs):
        for item in iterate(*args, **kwargs):
            el = item[-1]
            if getattr(el, "tag", None) == "F801":
                node = _find_node(el, "9B3A")
                payload = getattr(node, "payload", None) if node else None
                if payload:
                    try:
                        _parse_tables.folders = parse_tag_folders(
                            bytes(payload))
                    except Exception:  # noqa: BLE001 — never fail the open
                        _parse_tables.folders = []
            yield item

    def full_parse(*args, **kwargs):
        _parse_tables.folders = []          # this parse's, not the last one's
        return parse(*args, **kwargs)

    iter_top_level_lazy._keeps_folders = True
    full_parse._keeps_layers = getattr(parse, "_keeps_layers", False)
    _core.iter_top_level_lazy = iter_top_level_lazy
    _core.full_parse = full_parse
    return True


def tag_folder_records() -> list:
    """The last parse's tag folders for the importer: ``[{"key", "name",
    "parent", "hidden", "tags"}]`` with ``key``/``parent`` as strings and
    ``tags`` as tag NAMES (through the parse's id → name table); an id the
    table does not know is dropped. Empty for a file without folders."""
    table = getattr(_parse_tables, "layers", None) or {}
    out = []
    for f in getattr(_parse_tables, "folders", None) or ():
        out.append({
            "key": str(f["key"]),
            "name": f["name"] or "Folder",
            "parent": None if f["parent"] is None else str(f["parent"]),
            "hidden": bool(f["hidden"]),
            "tags": [table[i] for i in f["tags"] if i in table],
        })
    return out


#: Spellings of SketchUp's default tag: a face on it is on no layer.
_DEFAULT_TAGS = ("Layer0", "Layer 0", "Untagged")


def hidden_tags(names) -> frozenset:
    """The hidden tags ``names`` as the geometry may carry them: by name, and
    by the ids the last parse's table gives those names."""
    names = set(names)
    table = getattr(_parse_tables, "layers", None) or {}
    return frozenset(names | {i for i, n in table.items() if n in names})


def resolve_face_layers(model) -> int:
    """Turn the face layers that are tag ids into tag names, from the table
    of the parse that built ``model``. A face on the default tag, or on an
    id the table does not know, gets no layer. Returns how many changed."""
    table = getattr(_parse_tables, "layers", None) or {}
    definitions = dict(getattr(model, "definitions", {}) or {})
    if getattr(model, "root", None) is not None:
        definitions["ROOT"] = model.root
    for key, definition in definitions.items():
        for instance, pid in zip(getattr(definition, "instances", []),
                                 getattr(_parse_tables, "pids", {}).get(key, [])):
            instance.persistent_id = pid
        if getattr(definition, "is_group", False):
            _parse_tables.groups.add(definition.id)
        if hasattr(definition, "is_group"):
            _parse_tables.kinds = True
    changed = 0
    for defn in (getattr(model, "definitions", None) or {}).values():
        for face in (getattr(defn, "faces", None) or {}).values():
            lay = getattr(face, "layer", None)
            if isinstance(lay, bool) or not isinstance(lay, int):
                continue
            name = table.get(lay, "")
            face.layer = "" if name in _DEFAULT_TAGS else name
            changed += 1
    return changed


def _fix_definition_list_end(L) -> bool:
    original = getattr(L, "_read_entity_list_inner", None)
    if (original is None or getattr(original, "_ends_at_tail", False)
            or "burn_stack" not in original.__code__.co_names):
        return False

    def _read_entity_list_inner(ar, r, count, owner, ents):
        while len(ents) < count:
            p = r.pos
            inline = ar.inline_stack[-1] if getattr(ar, "inline_stack", None) else {}
            if (inline and len(ents) + len(inline) >= count
                    and L._peek_backref(ar, r) not in inline):
                break
            if (owner == 'def'
                    and struct.unpack_from('<I', r.data, p)[0] == 0
                    and r.data[p + 22:p + 25] == L._STR_MARKER):
                # the definition tail (nrel=0 + pad + 16-byte GUID + name
                # marker at +22): the list's REAL end, whatever was counted
                break
            prev_flag = ar.in_entity_list
            ar.in_entity_list = True
            try:
                s, n, v = ar.read_object(r)
            except L.LegacyParseError:
                if owner == 'root':
                    # over-declared root counts run into the document tail
                    r.pos = p
                    break
                if owner == 'def' and ar.burn_stack and ar.burn_stack[-1]:
                    r.pos = p
                    break
                raise
            finally:
                ar.in_entity_list = prev_flag
            inline.pop(s, None)
            ents.append((s, n, v))
        return ents

    _read_entity_list_inner._ends_at_tail = True
    L._read_entity_list_inner = _read_entity_list_inner
    return True


def _fix_layer_tail_2019(L) -> bool:
    # 1.5 checks the version for SketchUp 3, but still consumes only 21
    # tail bytes in 2019. Only our installed wrapper is known to handle it.
    original = getattr(L, "_read_layer", None)
    if original is None or getattr(original, "_long_tail", False):
        return False

    def _read_layer(ar, r):
        rec = original(ar, r)
        if getattr(ar, "ver", None) == 19 and r.peek(2) == b"\x00\x00":
            r.raw(2)
        return rec

    _read_layer._long_tail = True
    L._read_layer = _read_layer
    L._READERS['CLayer'] = _read_layer
    return True
