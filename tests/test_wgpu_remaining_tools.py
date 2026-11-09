"""Native tools retain the document command and cancellation contracts."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from tools.base import ToolContext
from tools.rotate import RotateTool
from core.camera import OrbitCamera
from tests.test_wgpu_mesh_tools import harness, click, event, geometry


def prepare(tool):
    scene, history, native, updates = harness(tool)
    native.camera = OrbitCamera()
    native.pick_face_any = lambda *args: (None, None)
    return scene, history, native, updates


def test_rotate_loose_matches_direct_command_and_cancel():
    def setup():
        scene, history, native, updates = prepare(RotateTool())
        face = scene.mesh.add_face([QVector3D(), QVector3D(2, 0, 0),
                                    QVector3D(0, 2, 0)])
        scene.select([face])
        native.update()
        return scene, history, native
    scene, history, native = setup()
    reference, ref_history, direct = setup()
    before = geometry(scene.mesh)
    for point in [(0, 0, 0), (2, 0, 0), (0, 2, 0)]:
        click(native, point)
        native.tool.on_release(native)
        ctx = ToolContext(direct, QVector3D(*point), QPointF(), Qt.NoModifier, None)
        direct.tool.on_hover(ctx)
        direct.tool.on_click(ctx)
        direct.tool.on_release(direct)
    assert type(history.undo_stack[-1]) is type(ref_history.undo_stack[-1])
    assert geometry(scene.mesh) == geometry(reference.mesh)
    after = geometry(scene.mesh)
    history.undo()
    native.update()
    assert geometry(scene.mesh) == before
    history.redo()
    native.update()
    assert geometry(scene.mesh) == after
    native.cancel()
    assert not native.view.overlay_primitives
