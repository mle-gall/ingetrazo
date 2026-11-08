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
    faces = ([f for f in owner.mesh.faces
              if f.attrs.get("ifc", {}).get("id") == obj["tag_id"]]
             if owner is not None else obj["faces"])
    guid = next((f.attrs["ifc"]["guid"] for f in faces
                 if f.attrs["ifc"].get("guid")), None)
    guid = guid or compressed_guid(uuid.uuid4())
    for face in faces:
        if face.attrs["ifc"].get("guid") != guid:
            face.attrs["ifc"] = {**face.attrs["ifc"], "guid": guid}
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
