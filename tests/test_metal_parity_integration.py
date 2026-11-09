"""P7 production handoffs, with unshown Qt event and resident range checks."""
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QVector3D, QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core.scene import Scene
from core.group import Group
from core.layers import Layer
from core.mesh import Mesh
from views.wgpu_scene import pack_scene, VERTEX
from views.wgpu_parity import face_ranges, has_transparency, hidden_geometry, preview_mesh
from views.wgpu_style import style_payload
from tests.test_metal_parity_input import view, face, pixel


def test_unpainted_with_unrelated_tag_effect_keeps_front_style():
    scene = Scene()
    scene.loose_mesh.add_face([QVector3D(), QVector3D(2,0,0), QVector3D(0,2,0)])
    scene.layers.append(Layer('unrelated', opacity=.25))
    p = pack_scene(scene)
    assert int(p.instances['info'][0, 1]) >> 24 == 0
    assert np.all(p.vertices['color'][:3, 3] == 0)
    assert style_payload(scene)['material_opacity']
    assert not has_transparency(p)


def test_hidden_rows_respect_filter_and_world_edits(view):
    f = face(view)
    view.scene.show_hidden_geometry = view.scene.show_hidden_objects = True
    f.attrs['hidden'] = True
    view.scene.mesh._mut_serial += 1
    group = Group(Mesh())
    group.mesh.add_face([QVector3D(), QVector3D(1,0,0), QVector3D(0,1,0)])
    group.hidden = True
    view.scene.groups.append(group)
    view.scene.version += 1
    view.set_scene(view.scene)
    calls = []
    view.renderer = SimpleNamespace(set_hidden_geometry=lambda *a: calls.append(a),
                                    update_instances=lambda *a: None)
    hidden_geometry(view)
    assert calls[-1][-1] == [view.packed.uids.index(group.uid)]
    assert np.frombuffer(calls[-1][2], view.packed.hidden_commands.dtype)['count'].sum() == 6
    view.tools.ids = np.array(calls[-1][-1], np.int64)
    rows = view.packed.instances[view.tools.ids].copy()
    rows['world'][:,3,0] += 2
    view.tools.write_rows(rows)
    assert len(calls) == 2
    assert view.packed.instances['world'][view.tools.ids[0],3,0] == 2
    group.layer = 'off'; view.scene.layers.append(Layer('off', visible=False))
    view.packed = pack_scene(view.scene)
    hidden_geometry(view)
    assert calls[-1][-1] == []


def test_face_ranges_and_native_marks_keep_pack(view):
    f = face(view)
    assert face_ranges(view, [f]) == [(0, 0, 2)]
    captured = []
    view.renderer = SimpleNamespace(set_highlight=lambda *a: None,
        set_face_marks=lambda a: captured.append(np.frombuffer(a, VERTEX).copy()))
    view.scene.select([f]); view.sync_selection()
    assert len(captured[-1]) == 6
    assert np.allclose(captured[-1]['pos'][:,2], 0)
    view.scene.clear_selection(); view.sync_selection()
    assert len(captured[-1]) == 0


def test_pushpull_recess_qt_events_suppress_without_repack(view, monkeypatch):
    from tools.pushpull import PushPullTool
    f = face(view)
    tool = PushPullTool()
    view.source_viewport.active_tool = tool
    view.tools.sync()
    # A bordered face uses the lightweight recess preview. A deterministic
    # drag-axis projection isolates native event/suppression lifetime from snap.
    point = pixel(view, QVector3D(1,1,0))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
    assert tool.dragging and tool.base_face is f
    tool._attached = True
    monkeypatch.setattr(tool, '_infer_reference_distance', lambda ctx: -.5)
    captured = dict(mesh=[], suppressed=[])
    view.renderer = SimpleNamespace(
        set_preview_mesh=lambda a,b: captured['mesh'].append((a.copy(),b.copy())),
        set_suppressed_faces=lambda a: captured['suppressed'].append(a),
        set_highlight=lambda *a: None, set_face_marks=lambda *a: None)
    original = view.packed
    # Keep the already established resident face pick for this synthetic host.
    move = QPointF(point.x()+10, point.y()+10)
    QApplication.sendEvent(view, QMouseEvent(QMouseEvent.MouseMove, move, move,
        Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert view.packed is original
    assert captured['suppressed'][-1] == [(0,0,2)]
    triangles = np.frombuffer(captured['mesh'][-1][0], VERTEX)
    assert len(triangles) and triangles['pos'][:,2].min() < -.49
    QTest.keyClick(view, Qt.Key_Escape)
    assert captured['suppressed'][-1] == []
    assert len(captured['mesh'][-1][0]) == 0
    assert not f.attrs.get('hidden')


def test_soft_pairs_and_opacity_survive_pack():
    scene = Scene()
    f = scene.mesh.add_face([QVector3D(), QVector3D(2,0,0), QVector3D(0,2,0)])
    f.attrs.update(color=(.2,.6,.4), opacity=.25, back=True)
    scene.mesh.edges[0].soft = True
    p = pack_scene(scene)
    assert has_transparency(p)
    assert len(p.profile_exclusions[0][1]) == 6
    assert p.materials.nbytes == 16  # matching backs use header bit, not corners
    assert p.materials.view('<u4')[3] == 1


def test_tape_and_eraser_reference_pickers(view):
    from core.guide import Guide
    from views.wgpu_inference import prepare
    f = face(view)
    view.scene.guides.append(Guide(QVector3D(0,1,0), QVector3D(1,0,0)))
    view.inference_index = prepare(view.packed, view.scene)
    x,y = view._world_to_pixel(QVector3D(1,1,0))
    assert view.tools.pick_guide(x,y) is view.scene.guides[0]
    x,y = view._world_to_pixel(QVector3D(1,0,0))
    assert view.tools.pick_axis(x,y) == 'x'
    edge = view.tools.pick_edge_any(x,y)
    assert edge is not None and not edge.in_group
    assert view.tools._nearby_loose_edges(x,y)


@pytest.mark.parametrize('crossing,zoom', [(False,False),(True,False),(False,True)])
def test_rectangle_qt_move_uses_directional_helper(view, crossing, zoom):
    from views.wgpu_overlay import selection_rectangle
    a,b = QPointF(100,100),QPointF(300,250)
    if crossing: a,b = b,a
    if zoom: view.source_viewport.nav_mode = 'zoom_window'
    QApplication.sendEvent(view,QMouseEvent(QMouseEvent.MouseButtonPress,a,a,
        Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
    QApplication.sendEvent(view,QMouseEvent(QMouseEvent.MouseMove,b,b,
        Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
    assert view.overlay_primitives == [selection_rectangle((a.x(),a.y()),(b.x(),b.y()),zoom=zoom)]


def test_loaded_soft_cylinder_has_shared_corner_normals():
    from pathlib import Path
    from formats.igz import load_into
    scene=Scene();load_into(scene,Path('docs/benchmarks/metal-parity/smooth.igz'))
    packed=pack_scene(scene)
    normals=packed.vertices['normal'][:int(packed.commands[0]['count'])].reshape(-1,3,3)
    assert np.any(np.linalg.norm(normals[:,0]-normals[:,1],axis=1) > .01)


from tests.test_metal_parity_raster import native


def test_native_opaque_opt_in_is_byte_identical_and_new_scene_resets(native):
    from tests.test_metal_parity_raster import upload, capture
    upload(native,255)
    native.set_material_transparency(False)
    native.set_style(dict(material_opacity=False,sky=False,edges=False,profiles=False))
    before=capture(native)
    native.set_style(dict(material_opacity=True,sky=False,edges=False,profiles=False))
    np.testing.assert_array_equal(before,capture(native))
    upload(native,64)  # unclassified raw scene must enable conservative OIT
    after=capture(native)
    assert after[32,32,2] > before[32,32,2]+50


def test_matching_back_header_renders_both_sides(native):
    from PySide6.QtGui import QMatrix4x4
    from tests.test_metal_parity_raster import capture
    scene=Scene()
    face=scene.mesh.add_face([QVector3D(-.8,-.8,0),QVector3D(.8,-.8,0),
                             QVector3D(.8,.8,0),QVector3D(-.8,.8,0)])
    face.attrs.update(color=(1.,0.,0.),back=True)
    packed=pack_scene(scene);assert packed.materials.view('<u4')[3] == 1
    packed.upload(native)
    native.set_style(dict(material_opacity=True,sky=False,edges=False,profiles=False))
    front=capture(native)[32,32,:3]
    view=QMatrix4x4();view.translate(0,0,-3);view.rotate(180,0,1,0)
    proj=QMatrix4x4();proj.ortho(-1,1,-1,1,.1,10)
    native.set_camera(list(view.data()),list(proj.data()))
    back=capture(native)[32,32,:3]
    assert front[0]>180 and back[0]>180
    assert front[1]<5 and back[1]<5



def test_eraser_guide_click_and_undo(view):
    from core.guide import Guide
    from tools.eraser import EraserTool
    face(view)
    guide=Guide(QVector3D(0,1,0),QVector3D(1,0,0))
    view.scene.guides.append(guide)
    view.source_viewport.active_tool=EraserTool()
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,pixel(view,QVector3D(1,1,0)))
    assert guide not in view.scene.guides
    view.source_viewport.history.undo()
    assert guide in view.scene.guides



def test_arc_uses_resident_tangent_without_gl_placement_scan(view):
    from tools.arc import ArcTool
    from views.wgpu_inference import prepare
    points=[QVector3D(np.cos(t),np.sin(t),0) for t in np.linspace(0,np.pi/2,9)]
    for a,b in zip(points,points[1:]):
        view.scene.mesh.add_edge(a,b).curve=42
    view.scene.version+=1;view.set_scene(view.scene)
    view.inference_index=prepare(view.packed,view.scene)
    view.tools._placements=lambda:pytest.fail('must not scan GL placements')
    tool=ArcTool();tool.start_point=points[0]
    direction=tool._tangent_at_start(view.tools)
    assert direction is not None and abs(direction.y()) > .999
