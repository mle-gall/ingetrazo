# SPDX-License-Identifier: GPL-3.0-or-later
"""Array consumers preserve topology and leave loaded geometry deferred."""
import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V, QMatrix4x4
from core.group import Group
from core.scene import Scene
from core.bim import (collect_objects, class_quantities, class_quantities_arrays,
                      face_set_area, face_set_volume, face_net_area,
                      _tagged_group_faces, tag_faces)
from core.geometry_arrays import arrays_of, world_arrays, merged, quantities


CUBE = [
    [(0,0,0),(0,1,0),(1,1,0),(1,0,0)],
    [(0,0,1),(1,0,1),(1,1,1),(0,1,1)],
    [(0,0,0),(1,0,0),(1,0,1),(0,0,1)],
    [(1,0,0),(1,1,0),(1,1,1),(1,0,1)],
    [(1,1,0),(0,1,0),(0,1,1),(1,1,1)],
    [(0,1,0),(0,0,0),(0,0,1),(0,1,1)],
]


def cube(split=False):
    g = Group()
    g.ifc = {'class': 'IfcWall', 'name': 'Cube'}
    a, b = (Group(), Group()) if split else (g, g)
    if split:
        g.children = [a, b]
    for i, points in enumerate(CUBE):
        (a if i < 3 else b).mesh.add_face([V(*p) for p in points])
    return g


def compare(g, excluded=()):
    a = merged(world_arrays(g, excluded=excluded))
    faces = _tagged_group_faces(g, None, excluded)
    area, net, volume, closed, count = quantities(a)
    assert area == pytest.approx(face_set_area(faces), rel=2e-6)
    assert net == pytest.approx(sum(face_net_area(f) for f in faces), rel=2e-6)
    assert volume == pytest.approx(face_set_volume(faces))
    assert closed == (volume is not None)
    assert count == len(faces)
    for cls in ('IfcWall', 'IfcSlab', 'IfcRoof', 'IfcStair', 'IfcRamp',
                'IfcColumn', 'IfcBeam', 'IfcFooting', 'IfcPile', 'IfcMember',
                'IfcRailing', 'IfcReinforcingBar', 'IfcCovering', 'IfcDoor',
                'IfcWindow', 'IfcSpace', 'IfcBuildingElementProxy'):
        expected = class_quantities(cls, faces)
        actual = class_quantities_arrays(cls, a)
        assert actual[0] == expected[0]
        assert [q[:2] for q in actual[1]] == [q[:2] for q in expected[1]]
        assert [q[2] for q in actual[1]] == pytest.approx([q[2] for q in expected[1]], rel=2e-6)
        assert actual[2][0] == pytest.approx(expected[2][0])
    return a


def test_split_closed_nested_and_anchor():
    g = cube(True)
    assert quantities(world_arrays(g))[2] == pytest.approx(1.)
    g.xform = QMatrix4x4()
    g.xform.translate(100000, 200000, -300000)
    parent = Group()
    parent.children = [g]
    g.ifc = None
    compare(parent)


def test_holes_open_and_cache_invalidation():
    g = Group()
    g.mesh.add_face([V(0,0,0),V(4,0,0),V(4,4,0),V(0,4,0)],
                    [[V(1,1,0),V(1,2,0),V(2,2,0),V(2,1,0)]])
    a = compare(g)
    assert quantities(a) == (16., 15., None, False, 1)
    old = arrays_of(g.mesh)
    assert arrays_of(g.mesh) is old
    g.mesh.add_face([V(10,0,0),V(11,0,0),V(10,1,0)])
    assert arrays_of(g.mesh) is not old


def test_tagged_descendants_and_excluded():
    g = cube(True)
    extra = cube()
    g.children.append(extra)
    assert quantities(world_arrays(g))[0] == 6
    extra.ifc = None
    compare(g, [extra.uid])


def test_legacy_loose_faces():
    scene = Scene()
    face = scene.loose_mesh.add_face([V(0,0,0),V(1,0,0),V(0,1,0)])
    tag_faces([face], 'IfcWall', 'Loose', 1)
    obj, = collect_objects(scene)
    assert obj['faces'] == [face]
    assert obj['area'] == .5
    assert 'arrays' not in obj


@pytest.mark.parametrize('schema', ['IFC4', 'IFC4X3_ADD2'])
@pytest.mark.parametrize('geometry', ['brep', 'polygonal'])
@pytest.mark.parametrize('closed', [True, False])
def test_export_readback(tmp_path, schema, geometry, closed):
    import ifcopenshell
    import ifcopenshell.validate
    from formats.ifc import save_ifc
    scene = Scene()
    g = cube(True) if closed else Group()
    if not closed:
        g.mesh.add_face([V(0,0,0),V(4,0,0),V(4,4,0),V(0,4,0)],
                        [[V(1,1,0),V(1,2,0),V(2,2,0),V(2,1,0)]])
        g.ifc = {'class': 'IfcWall'}
    scene.groups.append(g)
    scene.plugin_data['bim_registry'] = {'export_profiles': {'test': {'schema': schema, 'geometry': geometry}}}
    path = tmp_path / 'arrays.ifc'
    save_ifc(scene, path, profile='test')
    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger)
    assert not logger.statements
    if geometry == 'polygonal':
        item, = model.by_type('IfcPolygonalFaceSet')
        assert item.Closed == closed
        assert len(item.Faces) == (6 if closed else 1)
        if not closed:
            assert len(item.Faces[0].InnerCoordIndices) == 1
    else:
        assert len(model.by_type('IfcFace')) == (6 if closed else 1)
        assert bool(model.by_type('IfcClosedShell')) == closed


def test_loaded_takeoff_stays_deferred(tmp_path, monkeypatch):
    from formats import igz
    import core._native as native
    monkeypatch.setattr(igz, '_LARGE_DOCUMENT', 0)
    monkeypatch.setattr(igz, '_BULK_MIN', 1)
    monkeypatch.setattr(native, 'wanted', lambda: True)
    scene = Scene()
    scene.groups.append(cube())
    path = tmp_path / 'lazy.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    mesh = loaded.groups[0].mesh
    assert '_deferred' in mesh.__dict__
    obj, = collect_objects(loaded)
    assert obj['volume'] == pytest.approx(1.)
    class_quantities_arrays(obj['class'], obj['arrays']())
    assert '_deferred' in mesh.__dict__
