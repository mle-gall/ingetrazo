# SPDX-License-Identifier: GPL-3.0-or-later
"""Faceted bodies and local prototype maps without allocating Python faces."""
from core.bim import face_set_volume
from .step import _f

def _brep(w: object, faces, context_id: int) -> int:
    """Faceted geometry for a face set → IfcShapeRepresentation id. Closed
    sets become an IfcFacetedBrep; open ones an IfcShellBasedSurfaceModel."""
    point_ids: dict = {}

    def pt(v) -> int:
        key = (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
        pid = point_ids.get(key)
        if pid is None:
            pid = w.add("IFCCARTESIANPOINT",
                        f"({_f(key[0])},{_f(key[1])},{_f(key[2])})")
            point_ids[key] = pid
        return pid

    face_ids = []
    for f in faces:
        bounds = []
        outer = w.add("IFCPOLYLOOP",
                      "(" + ",".join(f"#{pt(v.position)}" for v in f.loop)
                      + ")")
        bounds.append(f"#{w.add('IFCFACEOUTERBOUND', f'#{outer}', '.T.')}")
        for h in f.hole_loops:
            loop = w.add("IFCPOLYLOOP",
                         "(" + ",".join(f"#{pt(v.position)}" for v in h) + ")")
            bounds.append(f"#{w.add('IFCFACEBOUND', f'#{loop}', '.T.')}")
        face_ids.append(w.add("IFCFACE", "(" + ",".join(bounds) + ")"))

    face_list = "(" + ",".join(f"#{i}" for i in face_ids) + ")"
    closed = face_set_volume(faces) is not None
    if closed:
        shell = w.add("IFCCLOSEDSHELL", face_list)
        item = w.add("IFCFACETEDBREP", f"#{shell}")
        rep_type = "'Brep'"
    else:
        shell = w.add("IFCOPENSHELL", face_list)
        item = w.add("IFCSHELLBASEDSURFACEMODEL", f"(#{shell})")
        rep_type = "'SurfaceModel'"
    w.last_shape_item = item
    return w.add("IFCSHAPEREPRESENTATION", f"#{context_id}", "'Body'",
                 rep_type, f"(#{item})")



def array_body(w, arrays, context_id, geometry='brep'):
    """Write array rings directly, batching coordinate formatting in NumPy."""
    import numpy as np
    from core.geometry_arrays import Arrays, merged, quantities
    a = arrays if isinstance(arrays, Arrays) else merged(arrays)
    closed = quantities(a)[3]
    pos, inverse = np.unique(np.round(a.pos[a.corners], 6), axis=0, return_inverse=True)
    coords = np.char.mod('%.6f', pos)
    rows = np.char.add(np.char.add(np.char.add(np.char.add(coords[:, 0], ','), coords[:, 1]), ','), coords[:, 2])
    if geometry == 'polygonal':
        point = w.entity('IfcCartesianPointList3D', CoordList='(' + ','.join(np.char.add(np.char.add('(', rows), ')')) + ')')
        refs = (inverse + 1).astype(str)
    else:
        ids = np.arange(w._next, w._next + len(pos))
        lines = np.char.add(np.char.add(np.char.add('#', ids.astype(str)), '=IFCCARTESIANPOINT(('), rows)
        w.stream.writelines(line + '));\n' for line in lines)
        w._next += len(pos)
        refs = np.char.add('#', ids[inverse].astype(str))
    rings, offset = [], 0
    for size in a.ring_sizes:
        rings.append('(' + ','.join(refs[offset:offset + size]) + ')')
        offset += size
    face_ids, offset = [], 0
    for count in a.ring_counts:
        loops = rings[offset:offset + count]
        offset += count
        if geometry == 'polygonal':
            if count == 1:
                face_ids.append(w.add('IFCINDEXEDPOLYGONALFACE', loops[0]))
            else:
                face_ids.append(w.add('IFCINDEXEDPOLYGONALFACEWITHVOIDS', loops[0], '(' + ','.join(loops[1:]) + ')'))
        else:
            bounds = []
            for i, loop in enumerate(loops):
                lid = w.add('IFCPOLYLOOP', loop)
                bounds.append(w.add('IFCFACEOUTERBOUND' if i == 0 else 'IFCFACEBOUND', f'#{lid}', '.T.'))
            face_ids.append(w.add('IFCFACE', '(' + ','.join(f'#{b}' for b in bounds) + ')'))
    face_list = '(' + ','.join(f'#{f}' for f in face_ids) + ')'
    if geometry == 'polygonal':
        item = w.add('IFCPOLYGONALFACESET', f'#{point}', '.T.' if closed else '.F.', face_list, '$')
        rep_type = "'Tessellation'"
    elif closed:
        shell = w.add('IFCCLOSEDSHELL', face_list)
        item = w.add('IFCFACETEDBREP', f'#{shell}')
        rep_type = "'Brep'"
    else:
        shell = w.add('IFCOPENSHELL', face_list)
        item = w.add('IFCSHELLBASEDSURFACEMODEL', f'(#{shell})')
        rep_type = "'SurfaceModel'"
    w.last_shape_item = item
    return w.add('IFCSHAPEREPRESENTATION', f'#{context_id}', "'Body'", rep_type, f'(#{item})')


def mapped_body(w, group, base, excluded, context_id, geometry, cache, axis):
    """Reuse local mesh bodies; prune ownership before mapping each occurrence.

    Element placements remain identity. Positive uniform orthogonal transforms
    map local prototypes into world metres; other transforms bake that occurrence.
    """
    import numpy as np
    from core.bim import _compose
    from core.group import np_affine
    from core.geometry_arrays import Arrays, arrays_of

    items = []

    def walk(placed, parent):
        matrix = _compose(parent, placed.xform)
        a = arrays_of(placed.mesh)
        if len(a.ring_counts):
            rot, trans = np_affine(matrix) if matrix is not None else (np.eye(3), np.zeros(3))
            scale = float(np.linalg.norm(rot[:, 0]))
            uniform = (scale > 1e-12 and np.linalg.det(rot) > 0 and
                       np.allclose((rot / scale).T @ (rot / scale), np.eye(3),
                                   rtol=1e-6, atol=1e-6))
            if uniform:
                key = id(placed.mesh)
                if key not in cache:
                    rep = array_body(w, a, context_id, geometry)
                    cache[key] = w.add('IFCREPRESENTATIONMAP', f'#{axis}', f'#{rep}')
                directions = [w.add('IFCDIRECTION', '(' + ','.join(_f(v) for v in col) + ')')
                              for col in (rot / scale).T]
                origin = w.add('IFCCARTESIANPOINT', '(' + ','.join(_f(v) for v in trans) + ')')
                transform = w.add('IFCCARTESIANTRANSFORMATIONOPERATOR3D',
                                  f'#{directions[0]}', f'#{directions[1]}',
                                  f'#{origin}', _f(scale) if scale >= 1e-6 else format(scale, '.15E'),
                                  f'#{directions[2]}')
                item = w.add('IFCMAPPEDITEM', f'#{cache[key]}', f'#{transform}')
            else:
                baked = Arrays((a.pos @ rot.T + trans).astype(np.float32).astype(float),
                               a.corners, a.ring_sizes, a.ring_counts, a.edge_face_counts)
                rep = array_body(w, baked, context_id, geometry)
                # A mapped identity wrapper permits mixed baked and shared bodies
                # in one MappedRepresentation, including open surface models.
                mapping = w.add('IFCREPRESENTATIONMAP', f'#{axis}', f'#{rep}')
                origin = w.add('IFCCARTESIANPOINT', '(0.,0.,0.)')
                transform = w.add('IFCCARTESIANTRANSFORMATIONOPERATOR3D', '$', '$', f'#{origin}', '1.', '$')
                item = w.add('IFCMAPPEDITEM', f'#{mapping}', f'#{transform}')
            items.append(item)
        for child in placed.children or ():
            if not child.ifc and child.uid not in excluded:
                walk(child, matrix)

    walk(group, base)
    # Style each occurrence, never the shared prototype.
    w.last_shape_item = items
    return w.add('IFCSHAPEREPRESENTATION', f'#{context_id}', "'Body'",
                 "'MappedRepresentation'", '(' + ','.join(f'#{i}' for i in items) + ')')
