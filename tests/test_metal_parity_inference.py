"""P6 device-free candidate contract; never constructs a renderer or a window.

Bounded offscreen ride measurement, 2026-11-09, same process/camera/pixels:
space_asbuilt_ride.igz, 1000x700 fitted overview, 66,874 visible placements.
Ten pixels over projected placement bounds, one warm-up pass then two passes
(20 measured samples per operation), 300-second subprocess deadline. Picked
rows were resolved before timing: these are CPU inference timings, NOT GPU
ID picking or end-to-end mouse-event latency. Common 12 px point tolerance;
no start-point/lock. GL uses its real _nearby_group_edges/_snap_scene and
compute_snap; baseline Metal is HEAD at 6b80e856 loaded into a separate module.

                            median ms     p95 ms       max ms
    Metal baseline snap        0.988       4.345        4.526
    P6 snap                    6.554      10.275       10.457
    GL snap                   17.443      30.898       31.466
    P6 nearby edges            3.655       4.765        4.868
    GL nearby edges            4.962       5.904        6.131

Index build: baseline 1.760 s; P6 4.606 s (background preparation contract).
Pack: 15.335 s. Uptime start: 15:18, up 8 days 9:07, load 6.10/13.36/15.58;
end: 15:19, up 8 days 9:08, load 6.19/11.97/14.89. Contended shared Mac.
Warm-cache numbers exclude the first screen-grid construction after a camera
change. Full viewport hover/pick performance is not established here.

Acceptance limitation: P6 improves this GL CPU path but DOES NOT meet the
requirement to beat the former single-picked-row Metal path. No claim of full
performance acceptance. P1 integration remains required; this package only
owns the helper API. Curve fits currently cover named source curves, not GL's
acquired unnamed face-boundary circle recognition. Hidden-face reveal still
depends on P3 supplying the corresponding triangles in the packed scene.

Validation: allowed 325-case batch once (320 passed, five no-tool/absent-index
fallback failures); those five passed after the guards were fixed. Final P6
file: 17 passed. Both native crates built in release, no target/debug created.
"""
from types import SimpleNamespace
import math
import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.guide import Guide
from views.wgpu_scene import pack_scene
from views.wgpu_inference import (prepare, snap, nearby_edges, reference_edge,
                                  tangent_direction, eligible_rows, surface)

app = QApplication.instance() or QApplication([])


def harness(scene):
    projection = QMatrix4x4()
    projection.ortho(-5, 5, -5, 5, .1, 100)
    matrix = QMatrix4x4()
    matrix.translate(0, 0, -10)
    camera = SimpleNamespace(target=QVector3D(), projection_matrix=lambda: projection,
                             view_matrix=lambda: matrix)
    view = SimpleNamespace(scene=scene, camera=camera, width=lambda: 1000,
                           height=lambda: 1000, packed=pack_scene(scene),
                           snap_threshold_px=9., edge_snap_threshold_px=14.)
    view._world_to_pixel = lambda p: ((p.x()+5)*100, (5-p.y())*100)
    view._pixel_to_ray = lambda x, y: (QVector3D(x/100-5, 5-y/100, 10), QVector3D(0, 0, -1))
    view.tools = SimpleNamespace(tool=None, work_point=lambda x, y: QVector3D(x/100-5, 5-y/100, 0))
    index = prepare(view.packed, scene)
    return view, index


def at(view, index, point, row=None, **options):
    return snap(index, row, view, *view._world_to_pixel(QVector3D(*point)), **options)


def near(view, index, point, **options):
    return nearby_edges(index, view.packed, view.camera, 1000, 1000,
                        *view._world_to_pixel(QVector3D(*point)), **options)


@pytest.mark.parametrize('point,kind', [((2, 2, 0), 'endpoint'),
    ((2, 0, 0), 'midpoint'), ((.4, .4, 0), 'on_face'), ((2, .7, 0), 'on_edge')])
def test_discrete_and_surface(point, kind):
    scene = Scene()
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0),
                        QVector3D(2, 2, 0), QVector3D(-2, 2, 0)])
    view, index = harness(scene)
    result = at(view, index, point, 0)
    assert result.kind == kind
    assert (result.point-QVector3D(*point)).length() < 1e-5


def test_cross_placement_endpoint_without_picked_row():
    scene = Scene()
    for x in [-2, 2]:
        mesh = Mesh()
        mesh.add_edge(QVector3D(x, 0, 0), QVector3D(x, 2, 0))
        scene.groups.append(Group(mesh))
    view, index = harness(scene)
    result = at(view, index, (2, 2, 0), 0)
    assert result.kind == 'endpoint'
    assert result.point == QVector3D(2, 2, 0)
    assert at(view, index, (2, 2, 0)).kind == 'endpoint'
    assert near(view, index, (2, 2, 0))[0].row == 1


def test_guide_intersection_point_and_line():
    scene = Scene()
    scene.guides = [Guide(QVector3D(1, 1, 0), QVector3D(1, 0, 0)),
                    Guide(QVector3D(1, 1, 0), QVector3D(0, 1, 0)), Guide(QVector3D(2, 2, 0))]
    view, index = harness(scene)
    assert at(view, index, (1, 1, 0)).kind == 'intersection'
    assert at(view, index, (2, 2, 0)).kind == 'endpoint'
    assert at(view, index, (2, 1, 0)).kind == 'on_line'


def test_synthetic_image_border_and_locked_policy():
    scene = Scene()
    plane = SimpleNamespace(locked=False, border_edges=lambda: [
        (QVector3D(-2, 1, 0), QVector3D(2, 1, 0))])
    scene.image_planes = [plane]
    scene.entity_selectable = lambda e: True
    view, index = harness(scene)
    assert at(view, index, (0, 1, 0)).kind == 'midpoint'
    plane.locked = True
    assert at(view, index, (0, 1, 0)).kind == 'none'


@pytest.mark.parametrize('grouped', [False, True])
@pytest.mark.parametrize('reveal', [False, True])
def test_hidden_and_soft_policy(grouped, reveal):
    scene = Scene()
    mesh = Mesh() if grouped else scene.mesh
    hidden = mesh.add_edge(QVector3D(-2, 0, 0), QVector3D(-2, 2, 0))
    hidden.hidden = True
    soft = mesh.add_edge(QVector3D(2, 0, 0), QVector3D(2, 2, 0))
    soft.soft = True
    if grouped:
        scene.groups.append(Group(mesh))
    scene.show_hidden_geometry = reveal
    view, index = harness(scene)
    assert bool(near(view, index, (-2, 1, 0))) == reveal
    assert bool(near(view, index, (2, 1, 0))) == (reveal or not grouped)


def test_rest_rows_and_incremental_global_ids():
    scene = Scene()
    for x in [-2, 2]:
        mesh = Mesh()
        mesh.add_edge(QVector3D(x, 0, 0), QVector3D(x, 2, 0))
        scene.groups.append(Group(mesh))
    view, index = harness(scene)
    base, proto = index.base, index.protos[1]
    view.packed.instances['world'][1, 3, 0] = -1
    index.update([1], view.packed)
    assert near(view, index, (1, 1, 0))[0].row == 1
    assert not near(view, index, (2, 1, 0))
    assert index.base is base and index.protos[1] is proto
    view.packed.instances['info'][1, 2] |= 64
    index.update([1], view.packed)
    assert near(view, index, (1, 1, 0))  # faded rest still supplies inference
    view.packed.instances['info'][1, 2] |= 128
    index.update([1], view.packed)
    assert eligible_rows(index).tolist() == [0]
    assert not near(view, index, (1, 1, 0))
    view.packed.instances['info'][1, 2] &= np.uint32(~np.uint32(128))
    index.update([1], view.packed)
    assert near(view, index, (1, 1, 0))[0].row == 1


def test_hidden_rest_surface_cannot_occlude():
    scene = Scene()
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0), QVector3D(0, 2, 0)])
    view, index = harness(scene)
    view.packed.instances['info'][0, 2] |= 64 | 128
    index.update([0], view.packed)
    assert surface(index, 0, QVector3D(0, 0, 10), QVector3D(0, 0, -1)) is None


def test_reference_edge_and_arc_tangent():
    scene = Scene()
    pts = [QVector3D(math.cos(t), math.sin(t), 0) for t in np.linspace(0, math.pi/2, 9)]
    for a, b in zip(pts, pts[1:]):
        scene.mesh.add_edge(a, b).curve = 42
    view, index = harness(scene)
    edge = reference_edge(index, view, *view._world_to_pixel((pts[0]+pts[1])*.5))
    assert edge is not None and edge.row == 0
    tangent = tangent_direction(index, view.packed, 0, pts[0])
    assert tangent is not None
    assert abs(QVector3D.dotProduct(tangent, QVector3D(1, 0, 0))) < 1e-4
    assert abs(tangent.y()) > .999
    assert tangent_direction(index, view.packed, 0, pts[4]) is None
    assert at(view, index, (0, 0, 0), 0).kind == 'center'


@pytest.mark.parametrize('mode,point', [('parallel', (2, 0, 0)),
                                      ('perpendicular', (0, 2, 0))])
def test_reference_locks_share_gl_rules(mode, point):
    scene = Scene()
    scene.mesh.add_edge(QVector3D(-2, -3, 0), QVector3D(2, -3, 0))
    view, index = harness(scene)
    edge = reference_edge(index, view, *view._world_to_pixel(QVector3D(0, -3, 0)))
    raw = QVector3D(*point)
    project = lambda s, d: s+d*QVector3D.dotProduct(raw-s, d)
    result = at(view, index, point, start_point=QVector3D(), reference_edge=edge,
                reference_mode=mode, project_onto_line=project,
                work_plane_normal=QVector3D(0, 0, 1))
    assert result.kind == 'reference'
    assert (result.point-raw).length() < 1e-5


def test_explicit_axis_lock_without_geometry():
    view, index = harness(Scene())
    result = at(view, index, (2, 1, 0), start_point=QVector3D(), axis_lock='x',
                project_onto_line=lambda s, d: QVector3D(2, 0, 0))
    assert result.kind == 'axis' and result.axis == 'x'
    assert result.point == QVector3D(2, 0, 0)
