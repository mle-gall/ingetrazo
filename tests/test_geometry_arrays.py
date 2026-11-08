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
    ifcopenshell = pytest.importorskip('ifcopenshell')
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
    ifcopenshell.validate.validate(model, logger, express_rules=True)
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
    for i, face in enumerate(scene.groups[0].mesh.faces):
        face.attrs['mat'] = 'Minority' if i == 0 else 'Majority'
    path = tmp_path / 'lazy.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    mesh = loaded.groups[0].mesh
    assert '_deferred' in mesh.__dict__
    obj, = collect_objects(loaded)
    assert obj['volume'] == pytest.approx(1.)
    assert '_deferred_plan' not in mesh.__dict__
    class_quantities_arrays(obj['class'], obj['arrays']())
    assert '_deferred' in mesh.__dict__
    from formats.ifc import save_ifc
    save_ifc(loaded, tmp_path / 'lazy.ifc')
    ifcopenshell = pytest.importorskip('ifcopenshell')
    model = ifcopenshell.open(str(tmp_path / 'lazy.ifc'))
    assert model.by_type('IfcMaterial')[0].Name == 'Majority'
    assert '_deferred' in mesh.__dict__


@pytest.mark.parametrize("reverse_holes", [False, True])
def test_closed_shell_with_holes(reverse_holes):
    g = Group()
    outer = [(0,0), (3,0), (3,3), (0,3)]
    inner = [(1,1), (2,1), (2,2), (1,2)]
    for z, reverse in ((0, True), (1, False)):
        ring = [V(x,y,z) for x,y in outer]
        hole = [V(x,y,z) for x,y in reversed(inner)]
        if reverse:
            ring.reverse()
            hole.reverse()
        g.mesh.add_face(ring, [hole])
    for ring in (outer, list(reversed(inner))):
        for i, (x,y) in enumerate(ring):
            xx, yy = ring[(i+1) % 4]
            g.mesh.add_face([V(x,y,0),V(xx,yy,0),V(xx,yy,1),V(x,y,1)])
    if reverse_holes:
        for face in g.mesh.faces:
            for hole in face.hole_loops:
                hole.reverse()
    assert quantities(compare(g))[2] == pytest.approx(8)


def test_untagged_loose_mesh_stays_deferred(tmp_path, monkeypatch):
    from formats import igz
    import core._native as native
    monkeypatch.setattr(igz, '_LARGE_DOCUMENT', 0)
    monkeypatch.setattr(igz, '_BULK_MIN', 1)
    monkeypatch.setattr(native, 'wanted', lambda: True)
    scene = Scene()
    for points in CUBE:
        scene.loose_mesh.add_face([V(*p) for p in points])
    path = tmp_path / 'loose.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    assert '_deferred' in loaded.loose_mesh.__dict__
    assert collect_objects(loaded) == []
    assert '_deferred' in loaded.loose_mesh.__dict__


def test_deferred_face_tags_inside_group_and_identity(tmp_path, monkeypatch):
    from formats import igz
    from formats.ifc import save_ifc
    ifcopenshell = pytest.importorskip('ifcopenshell')
    import core._native as native
    monkeypatch.setattr(igz, '_LARGE_DOCUMENT', 0)
    monkeypatch.setattr(igz, '_BULK_MIN', 1)
    monkeypatch.setattr(native, 'wanted', lambda: True)
    scene = Scene()
    g = cube()
    g.ifc = None
    tag_faces(g.mesh.faces, 'IfcWall', 'Face-tagged cube', 1)
    g.xform = QMatrix4x4()
    g.xform.translate(3, 4, 5)
    scene.groups.append(g)
    path = tmp_path / 'tags.igz'
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    mesh = loaded.groups[0].mesh
    obj, = collect_objects(loaded)
    assert 'faces' not in obj
    assert obj['volume'] == pytest.approx(1)
    assert obj['arrays']().pos[:, 0].min() == 3
    assert '_deferred' in mesh.__dict__
    out = tmp_path / 'tags.ifc'
    save_ifc(loaded, out)
    guid = ifcopenshell.open(str(out)).by_type('IfcWall')[0].GlobalId
    assert '_deferred' in mesh.__dict__
    igz.save_scene(loaded, path)
    reloaded = Scene()
    igz.load_into(reloaded, path)
    save_ifc(reloaded, out)
    assert ifcopenshell.open(str(out)).by_type('IfcWall')[0].GlobalId == guid
    assert '_deferred' in reloaded.groups[0].mesh.__dict__


def test_separately_closed_placements_skip_weld(monkeypatch):
    import core.geometry_arrays as ga
    root = Group()
    root.children = [cube(), cube()]
    for i, child in enumerate(root.children):
        child.ifc = None
        child.xform = QMatrix4x4()
        child.xform.translate(i * 3, 0, 0)
    def fail(*args):
        raise AssertionError('closed placements must not weld')
    monkeypatch.setattr(ga, 'merged', fail)
    assert ga.quantities(ga.world_arrays(root))[2:4] == (2., True)


@pytest.mark.parametrize('geometry', ['brep', 'polygonal'])
def test_mapped_instances_world_readback(tmp_path, geometry):
    ifcopenshell = pytest.importorskip('ifcopenshell')
    import ifcopenshell.geom
    import ifcopenshell.validate
    from formats.ifc import save_ifc
    scene = Scene()
    first = cube()
    for i in range(4):
        g = Group()
        g.mesh = first.mesh
        g.ifc = {'class': 'IfcWall'}
        g.xform = QMatrix4x4()
        g.xform.translate(i * 10, 2, 3)
        if i == 2:
            g.xform.scale(-1, 1, 1)
        elif i == 3:
            g.xform.scale(2, 1, 1)
        scene.groups.append(g)
    scene.plugin_data['bim_registry'] = {'export_profiles': {'test': {
        'geometry': geometry, 'instancing': True}}}
    path = tmp_path / 'mapped.ifc'
    assert save_ifc(scene, path, profile='test') == 4
    model = ifcopenshell.open(str(path))
    assert len(model.by_type('IfcRepresentationMap')) == 3
    assert len(model.by_type('IfcMappedItem')) == 4
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert not logger.statements
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    iterator = ifcopenshell.geom.iterator(settings, model)
    bounds = []
    assert iterator.initialize()
    while True:
        shape = iterator.get()
        points = np.asarray(shape.geometry.verts).reshape(-1, 3)
        bounds.append((points.min(axis=0), points.max(axis=0)))
        if not iterator.next():
            break
    bounds.sort(key=lambda b: b[0][0])
    assert len(bounds) == 4
    assert np.asarray([b[0] for b in bounds]) == pytest.approx(
        np.array([[0,2,3],[10,2,3],[19,2,3],[30,2,3]]))
    assert np.asarray([b[1] for b in bounds]) == pytest.approx(
        np.array([[1,3,4],[11,3,4],[20,3,4],[32,3,4]]))


def test_step_writer_streams_in_order():
    from io import StringIO
    from formats.ifc.step import _Writer
    sink = StringIO()
    writer = _Writer(sink)
    assert writer.add('IFCCARTESIANPOINT', '(0.,0.,0.)') == 1
    assert sink.getvalue() == '#1=IFCCARTESIANPOINT((0.,0.,0.));\n'
    assert writer.add('IFCAXIS2PLACEMENT3D', '#1', '$', '$') == 2
    assert sink.getvalue().endswith('#2=IFCAXIS2PLACEMENT3D(#1,$,$);\n')
    assert not hasattr(writer, 'lines')


def test_mapped_ownership_excludes_tagged_and_opening_children(tmp_path):
    ifcopenshell = pytest.importorskip('ifcopenshell')
    from formats.ifc import save_ifc
    scene = Scene()
    host = cube()
    opening = cube()
    opening.ifc = None
    tagged = cube()
    host.children = [opening, tagged]
    host.ifc['openings'] = [{'group_uid': opening.uid}]
    scene.groups = [host]
    scene.plugin_data['bim_registry'] = {'export_profiles': {'test': {'instancing': True}}}
    path = tmp_path / 'ownership.ifc'
    assert save_ifc(scene, path, profile='test') == 2
    model = ifcopenshell.open(str(path))
    assert len(model.by_type('IfcMappedItem')) == 2
    assert len(model.by_type('IfcOpeningElement')) == 1


def test_loose_edges_do_not_open_closed_solid():
    g = cube()
    g.mesh.add_edge(V(5,0,0), V(6,0,0))
    assert quantities(world_arrays(g))[2:4] == (1., True)


def test_mapping_tiny_scales_preserve_uniformity_and_scale(tmp_path):
    ifcopenshell = pytest.importorskip('ifcopenshell')
    from formats.ifc import save_ifc
    scene = Scene()
    prototype = cube()
    for scale in ((1e-8, 1e-8, 1e-8), (1e-6, 2e-6, 1e-6)):
        g = Group(prototype.mesh)
        g.ifc = {'class': 'IfcWall'}
        g.xform = QMatrix4x4()
        g.xform.scale(*scale)
        scene.groups.append(g)
    scene.plugin_data['bim_registry'] = {'export_profiles': {'test': {'instancing': True}}}
    path = tmp_path / 'tiny.ifc'
    save_ifc(scene, path, profile='test')
    model = ifcopenshell.open(str(path))
    maps = model.by_type('IfcRepresentationMap')
    assert len(maps) == 2
    scales = [m.MappingTarget.Scale for m in model.by_type('IfcMappedItem')]
    assert scales == pytest.approx([1e-8, 1.])


@pytest.mark.parametrize('scale', [(2,2,2), (-2,2,2), (2,3,4), (1e-6,2e-6,1e-6)])
def test_prototype_placement_quantities_match_world(scale):
    from core.geometry_arrays import owned_placements, placement_quantities
    g = cube()
    g.xform = QMatrix4x4()
    g.xform.scale(*scale)
    actual = placement_quantities(list(owned_placements(g)))
    reference = list(world_arrays(g))
    for arrays in reference:
        arrays._measurements = None
    expected = quantities(reference)
    assert actual[:3] == pytest.approx(expected[:3], rel=2e-6, abs=1e-25)
    assert actual[3:] == expected[3:]


def test_direct_source_preserves_distinct_coincident_points(monkeypatch):
    from core.mesh import Mesh, DeferredMesh
    from core.geometry_arrays import Arrays
    import core.lazy_mesh as lazy
    # Two coincident triangles with distinct saved vertex identities are two
    # open sheets, not a welded closed two-sided surface.
    mesh = Mesh()
    pos = np.array([[0,0,0],[1,0,0],[0,1,0]] * 2, dtype=float)
    source = dict(pos=pos, rings=np.arange(6), sizes=np.array([3,3]),
                  counts=np.array([1,1]), sequential=True, meta={'arrays': {}})
    DeferredMesh.defer(mesh, lambda m: None, 2, source)
    def fail(*args, **kwargs):
        raise AssertionError('indexed source must not plan or weld')
    monkeypatch.setattr(lazy, 'plan', fail)
    monkeypatch.setattr(lazy, 'weld', fail)
    assert quantities(arrays_of(mesh)) == (1., 1., None, False, 2)
    assert '_deferred_plan' not in mesh.__dict__


def test_collect_reuses_prototype_measurements_and_split_closure(monkeypatch):
    import core.geometry_arrays as ga
    prototype = cube()
    scene = Scene()
    for i in range(5):
        g = Group(prototype.mesh)
        g.ifc = {'class': 'IfcWall'}
        g.xform = QMatrix4x4()
        g.xform.translate(i * 3, 0, 0)
        scene.groups.append(g)
    calls = []
    original = ga.ring_data
    def counted(a):
        calls.append(a)
        return original(a)
    monkeypatch.setattr(ga, 'ring_data', counted)
    assert [o['volume'] for o in collect_objects(scene)] == [1.] * 5
    assert len(calls) == 1
    scene.groups = [cube(True)]
    assert collect_objects(scene)[0]['volume'] == pytest.approx(1.)


def test_tag_cache_invalidates_on_tag_epoch():
    from core.bim import _holds_face_tags, untag_faces
    g = cube()
    assert not _holds_face_tags(g.mesh)
    tag_faces(g.mesh.faces, 'IfcWall', 'Tagged', 1)
    assert _holds_face_tags(g.mesh)
    untag_faces(g.mesh.faces)
    assert not _holds_face_tags(g.mesh)
