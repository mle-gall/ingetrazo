# SPDX-License-Identifier: GPL-3.0-or-later
"""World-space faceted geometry, shared by both export schemas."""
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
        w.lines.extend(np.char.add(lines, '));').tolist())
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
