"""Cooperative, detached snapshots for background IGZ recovery writes.

Only the UI thread reads the model. Geometry and metadata cross into the
worker as owned numeric arrays / Python values, never live meshes or widgets. Survey images use owned QImage values.
"""
from array import array
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class Geometry:
    arrays: dict | None = None
    attrs: list | None = None
    layers: list | None = None
    deferred: dict | None = None


def copy_steps(value):
    """Copy nested serializer metadata, yielding between small pieces."""
    import numpy as np
    if isinstance(value, (Geometry, Survey)):
        return value                    # already owned by this snapshot
    if isinstance(value, np.ndarray):
        out = np.empty(value.shape, dtype=value.dtype)
        if not value.ndim:
            out[...] = value
        else:
            stride = max(1, (256 * 1024) // max(1, value[0:1].nbytes))
            for i in range(0, len(value), stride):
                out[i:i + stride] = value[i:i + stride]
                yield
        return out
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = yield from copy_steps(v)
            yield
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.append((yield from copy_steps(v)))
            yield
        return out
    return value                       # JSON scalars, bytes, strings


def geometry_steps(mesh):
    from core.mesh import DeferredMesh
    from formats.igz import _face_attrs_json
    if type(mesh) is DeferredMesh:
        source = yield from copy_steps(mesh.__dict__["_deferred_source"])
        return {"geom": Geometry(deferred=source)}
    if not mesh.edges and not mesh.faces:
        return {"edges": [], "faces": []}
    pos, edges, rings = array('f'), array('i'), array('i')
    sizes, counts, face_attr = array('i'), array('i'), array('i')
    flags, curves, layers = array('B'), array('q'), array('i')
    vertices, attr_index, layer_index = {}, {}, {}
    attrs, layer_names = [], []

    def vertex(v):
        key = id(v)
        if key not in vertices:
            vertices[key] = len(vertices)
            pos.extend(v.position.toTuple())
        return vertices[key]

    for i, e in enumerate(mesh.edges):
        edges.extend((vertex(e.v0), vertex(e.v1)))
        flags.append(int(e.soft) | (int(e.hidden) << 1))
        curves.append(-1 if e.curve is None else e.curve)
        layer = e.layer
        if layer is None:
            layers.append(-1)
        else:
            if layer not in layer_index:
                layer_index[layer] = len(layer_names)
                layer_names.append(layer)
            layers.append(layer_index[layer])
        if i % 128 == 0:
            yield
    for i, f in enumerate(mesh.faces):
        holes = f.hole_loops or ()
        if len(holes) > 1:
            from core.topology import _maximal_holes
            from PySide6.QtGui import QVector3D
            polys = [[QVector3D(v.position) for v in h] for h in holes]
            kept = {id(h) for h in _maximal_holes(polys)}
            holes = [h for h, p in zip(holes, polys) if id(p) in kept]
        counts.append(1 + len(holes))
        for loop in [f.loop] + list(holes):
            sizes.append(len(loop))
            for j, v in enumerate(loop):
                rings.append(vertex(v))
                if j and j % 256 == 0:
                    yield
        attr = _face_attrs_json(f) if f.attrs else None
        if attr:
            # Only this small record is encoded on the UI thread.
            import json
            key = json.dumps(attr, sort_keys=True, separators=(',', ':'))
            if key not in attr_index:
                attr_index[key] = len(attrs)
                attrs.append((yield from copy_steps(attr)))
            face_attr.append(attr_index[key])
        else:
            face_attr.append(-1)
        if i % 64 == 0:
            yield
    # A large prototype's vertex index can hold millions of Python ints.
    # Letting the generator destroy it all at return makes one long UI
    # pause even though capture itself yielded regularly. Retire in slices.
    while vertices:
        for _ in range(min(1024, len(vertices))):
            vertices.popitem()
        yield
    arrays = dict(pos=pos, edges=edges, rings=rings, ring_sizes=sizes,
                  ring_counts=counts, face_attr=face_attr, edge_flags=flags,
                  edge_curve=curves, edge_layer=layers)
    return {"geom": Geometry(arrays, attrs, layer_names)}


def snapshot_steps(scene):
    from formats.igz import prepare_scene_steps
    # Shared prototypes, and classic groups sharing a mesh, are captured once.
    meshes = {}
    def capture(mesh):
        if id(mesh) not in meshes:
            meshes[id(mesh)] = yield from geometry_steps(mesh)
        # The entry itself receives group metadata, so it must be distinct.
        return dict(meshes[id(mesh)])
    # Editing swaps scene.mesh to the active group. Recover the entire
    # document, not a second loose copy of that group. Its current world
    # mesh already lives in the group tree and is captured there.
    import copy
    document = copy.copy(scene)
    root = getattr(scene, "_loose_mesh", None)
    if root is not None:
        document.mesh = root
    prepared = yield from prepare_scene_steps(document, capture)
    return (yield from copy_steps(prepared))


def resolve_geometry(payload, sink):
    """Worker-only: encode captured arrays into the usual format-3 blocks."""
    import numpy as np
    from formats.igz import (_write_geometry, _pack_plan, _bulk_sized,
                             NonFiniteDocumentError)
    encoded = {}
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            snapshot = node.get('geom')
            if isinstance(snapshot, Geometry):
                hit = encoded.get(id(snapshot))
                if hit is None:
                    if snapshot.deferred is not None:
                        from core.lazy_mesh import plan
                        src = snapshot.deferred
                        p = plan(src['pos'], src['edges'], src['flags'],
                                 src['curves'], src['layers'],
                                 src['meta'].get('edge_layers') or [],
                                 src['rings'], src['sizes'], src['counts'],
                                 src.get('sequential', False))
                        mesh = SimpleNamespace(_deferred_source=src)
                        hit = _pack_plan(mesh, p, sink)
                        if not _bulk_sized(len(p.edges), p.nfaces):
                            hit['sequential'] = True
                    else:
                        arrays = {k: np.asarray(v) for k,v in snapshot.arrays.items()}
                        arrays['pos'] = arrays['pos'].reshape(-1, 3)
                        arrays['edges'] = arrays['edges'].reshape(-1, 2)
                        if not np.isfinite(arrays['pos']).all():
                            raise NonFiniteDocumentError('geometry')
                        hit = _write_geometry(arrays, snapshot.attrs,
                                              snapshot.layers, sink)
                        if not _bulk_sized(len(arrays['edges']),
                                           len(arrays['ring_counts'])):
                            hit['sequential'] = True
                    encoded[id(snapshot)] = hit
                node['geom'] = hit
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


@dataclass
class Survey:
    mesh: object


def survey_steps(source):
    from PySide6.QtGui import QImage
    import copy
    mesh = SimpleNamespace()
    for name in ('vertices', 'uvs', 'triangles'):
        setattr(mesh, name, (yield from copy_steps(getattr(source, name))))
    for name in ('materials', 'source', 'anchor', 'visible', 'layer', 'vertical_reference'):
        setattr(mesh, name, copy.deepcopy(getattr(source, name)))
        yield
    # QImage's implicit sharing detaches on edits; no GUI resources are used.
    mesh.images = {key: QImage(image) for key, image in source.images.items()}
    return Survey(mesh)
