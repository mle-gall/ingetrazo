"""Metal texture gestures share GL commands and replace only touched UVs."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh
from tools.base import ToolContext
from tools.texture_position import TexturePositionTool
from views.wgpu_overlay import rasterize, pixels
from views.wgpu_scene import pack_scene
from views.wgpu_updates import InstanceUpdates
from tests.test_wgpu_mesh_tools import harness


def setup():
    scene, history, native, _ = harness(TexturePositionTool())
    for x in (0, 4):
        mesh = Mesh()
        mesh.add_faces_bulk(np.array([[x, 0, 0], [x+2, 0, 0], [x+2, 2, 0], [x, 2, 0]], np.float64),
                            [4], [1], [{'texture': {'path': 'brick.png', 'sw': 1., 'sh': 1.}}])
        scene.groups.append(Group(mesh))
    scene.begin_group_edit(scene.groups[0])
    packed = pack_scene(scene)
    tracker = InstanceUpdates(scene, packed)
    tracker.observe(history)
    calls = []
    renderer = SimpleNamespace(update_prototype_materials=lambda code, data: calls.append((code, data.copy())))
    native.view.packed = packed
    native.view.renderer = renderer
    native.view._instance_updates = tracker
    native.view.set_scene = lambda scene: tracker.apply(*tracker.diff(scene))
    native.view._world_to_pixel = lambda p: (p.x()*50+20, p.y()*50+20)
    native.view._pixel_to_ray = lambda x, y: (QVector3D((x-20)/50, (y-20)/50, 10), QVector3D(0, 0, -1))
    native.source = native.view.source_viewport
    from views.viewport import Viewport
    native.source.GRAZING_PLANE_DEG = Viewport.GRAZING_PLANE_DEG
    native.source._ray_plane = lambda *a: Viewport._ray_plane(native, *a)
    native.pick_face = lambda *a: scene.mesh.faces[0]
    native.tool.begin(native, scene.mesh.faces[0], QVector3D(.2, .2, 0))
    return scene, history, native, tracker, calls


@pytest.mark.parametrize('pin', [0, 1, 2])
@pytest.mark.parametrize('modifiers', [Qt.NoModifier, Qt.ControlModifier])
def test_gesture_commit_equals_gl_and_one_prototype_undo_redo(pin, modifiers):
    scene, history, native, tracker, calls = setup()
    face = native.tool.face
    from views.viewport import Viewport
    gl = Viewport(None)
    gl.flash_status = lambda *a: None
    gl._world_to_pixel = native._world_to_pixel
    gl._pixel_to_ray = native._pixel_to_ray
    gl_face = gl.scene.mesh.add_face(list(face.vertices))
    gl_face.attrs = {'texture': dict(face.attrs['texture'])}
    direct = TexturePositionTool()
    gl.set_active_tool(direct)
    direct.begin(gl, gl_face, QVector3D(.2, .2, 0))
    start = native.tool.pins()[pin]
    end = start + QVector3D(.3, .4, 0)
    for tool, viewport in ((direct, gl), (native.tool, native)):
        for handler, point in ((tool.on_click, start), (tool.on_hover, end)):
            ctx = ToolContext(viewport, point, QPointF(*native._world_to_pixel(point)), modifiers, None)
            if viewport is native:
                native.view.last_snap = SimpleNamespace(point=point, kind=None)
                event = SimpleNamespace(position=lambda: ctx.screen, modifiers=lambda: modifiers)
                (native.click if handler == tool.on_click else native.hover)(event)
            else:
                handler(ctx)
        tool.on_release(viewport)
    expected = direct.result_texture()
    original = dict(face.attrs['texture'])
    assert face.attrs['texture'] == original  # preview does not edit the face
    native.tool.commit(native)
    direct.commit(gl)
    assert face.attrs['texture'] == gl_face.attrs['texture'] == expected
    assert type(history.undo_stack[-1]) is type(gl.history.undo_stack[-1])
    assert len(tracker.changed) == 1
    assert tracker.changed[0][0] is scene.mesh
    history.undo()
    tracker.apply(*tracker.diff(scene))
    assert face.attrs['texture'] == original
    assert len(tracker.changed) == 1
    history.redo()
    tracker.apply(*tracker.diff(scene))
    assert face.attrs['texture'] == expected
    assert len(tracker.changed) == 1
    gl.close()


def test_preview_upload_is_local_and_escape_clears_handles():
    scene, history, native, tracker, calls = setup()
    tool = native.tool
    original = dict(tool.face.attrs['texture'])
    before = rasterize([], 160, 160, 1, lambda p: tool.draw_overlay(native, p))
    assert pixels(before).any()
    original_stream = calls[-1][1].copy()
    serial = scene.mesh._mut_serial
    tool.map.R += QVector3D(.2, 0, 0)
    native.update()
    assert not np.array_equal(calls[-1][1], original_stream)
    assert scene.mesh._mut_serial == serial
    assert calls
    assert {code for code, _ in calls} == {tracker.meshes[id(scene.mesh)][2]}
    assert tool.face.attrs['texture'] == original
    native.cancel()  # GL semantics: restore first, leave on second Escape.
    native.cancel()
    after = rasterize([], 160, 160, 1, lambda p: tool.draw_overlay(native, p))
    assert not pixels(after).any()
    assert not tool.pins()


def test_slow_preview_defers_until_release_and_back_material_undo():
    scene, history, native, tracker, calls = setup()
    tool = native.tool
    face = tool.face
    face.attrs['back'] = {'texture': dict(face.attrs['texture'])}
    tool.begin(native, face, QVector3D(.2, .2, 0), side='back')
    preview = native.view._texture_preview
    preview.overlay_only = True
    count = len(calls)
    tool._drag = ('texture', tool.map.copy(), list(tool.pin_uv))
    tool.map.R += QVector3D(.1, .2, 0)
    preview.update(tool)
    assert len(calls) == count
    tool._drag = None
    preview.update(tool)
    assert len(calls) == count + 1
    expected = tool.result_texture()
    tool.commit(native)
    assert face.attrs['back']['texture'] == expected
    assert len(tracker.changed) == 1
    history.undo()
    tracker.apply(*tracker.diff(scene))
    assert 'uvw' not in face.attrs['back']['texture']
    assert len(tracker.changed) == 1


def test_undo_after_leaving_edit_context_keeps_material_target():
    scene, history, native, tracker, calls = setup()
    mesh = scene.mesh
    native.tool.map.R += QVector3D(.2, 0, 0)
    native.tool.commit(native)
    scene.end_group_edit()
    tracker.apply(*tracker.diff(scene))
    history.undo()
    tracker.diff(scene)
    assert [entry[0] for entry in tracker.changed] == [mesh]
