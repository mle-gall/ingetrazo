# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Persistent IFC identities for elements and document-owned relationships."""
import json
import uuid

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def compressed_guid(value):
    n = value.int
    return "".join(_CHARS[(n >> (6 * i)) & 63] for i in range(21, -1, -1))


def stable_guid(namespace, *parts):
    key = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return compressed_guid(uuid.uuid5(uuid.UUID(namespace), key))


def ensure_guid(tag):
    if not tag.get("guid"):
        tag["guid"] = compressed_guid(uuid.uuid4())
    return tag["guid"]


def object_guid(scene, obj):
    group = obj.get("group")
    if group is not None:
        tag = group.ifc
        before = tag.get("guid")
        result = ensure_guid(tag)
        if before != result:
            scene.version += 1
        return result
    owner = obj.get("owner")
    # Shared definitions cannot store a placement's GUID on their faces.
    if owner is not None:
        from core.mesh import DeferredMesh
        if type(owner.mesh) is DeferredMesh:
            # Persist into the deferred document metadata, so both building
            # and saving later see the identity without building faces now.
            src = owner.mesh.__dict__["_deferred_source"]
            table = src["meta"].get("face_attrs") or []
            attributes = [table[i] for i in dict.fromkeys(src["face_attr"]) if i >= 0]
        else:
            attributes = [f.attrs for f in owner.mesh.faces]
        attributes = [a for a in attributes
                      if a.get("ifc", {}).get("id") == obj["tag_id"]]
    else:
        attributes = [f.attrs for f in obj["faces"]]
    guid = next((a["ifc"]["guid"] for a in attributes
                 if a["ifc"].get("guid")), None)
    guid = guid or compressed_guid(uuid.uuid4())
    for attrs in attributes:
        if attrs["ifc"].get("guid") != guid:
            attrs["ifc"] = {**attrs["ifc"], "guid": guid}
            scene.version += 1
    if owner is not None:
        return stable_guid(scene.plugin_data["ifc_identity"]["namespace"],
                           "faces", owner.uid, guid)
    return guid


def copied_face_attrs(scene=None):
    """One remapper per placed copy, keeping faces of one object together."""
    # Copies can be planned before any command enters the scene (arrays).
    # Random integer ids avoid reserving mutable document state while planning.
    next_id = uuid.uuid4().int >> 80
    tags = {}

    def copy_attrs(attrs):
        nonlocal next_id
        out = dict(attrs or {})
        tag = out.get("ifc")
        if tag:
            key = tag.get("id")
            if key not in tags:
                tags[key] = {k: v for k, v in tag.items() if k != "guid"}
                tags[key]["id"] = next_id
                next_id += 1
                ensure_guid(tags[key])
            out["ifc"] = dict(tags[key])
        return out
    return copy_attrs
