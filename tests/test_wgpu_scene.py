"""The resident-scene ABI is testable without a native window or GPU."""
import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from core import _native
from views.wgpu_scene import pack_scene, VERTEX, INSTANCE, COMMAND

pytestmark = pytest.mark.skipif(_native.available() is None, reason='native kernel required')


def triangle():
    mesh = Mesh()
    mesh.add_face([QVector3D(*p) for p in [(0, 0, 0), (2, 0, 0), (0, 3, 0)]])
    return mesh


def test_layout():
    assert (VERTEX.itemsize, INSTANCE.itemsize, COMMAND.itemsize) == (28, 80, 20)
    assert INSTANCE.fields['info'][1] == 64
    assert COMMAND.fields['start'][1] == 16


def test_shared_mesh_bounds_and_column_major():
    mesh = triangle()
    a, b = Group(mesh), Group(mesh)
    b.xform = QMatrix4x4()
    b.xform.translate(10, 20, 30)
    b.xform.scale(-2, 3, 1)
    packed = pack_scene(Scene(groups=[a, b]))
    assert len(packed.vertices) == 3
    assert len(packed.bounds) == 1
    assert len(packed.instances) == 2
    assert packed.commands['count'].tolist() == [3]
    assert packed.commands['start'].tolist() == [0]
    np.testing.assert_array_equal(packed.bounds[0, :, :3], [[0, 0, 0], [2, 3, 0]])
    np.testing.assert_array_equal(packed.instances['world'][1].ravel(), b.xform.data())
    np.testing.assert_array_equal(packed.world_bounds, [[0, 0, 0], [10, 29, 30]])


def test_empty_and_explicit_color():
    assert len(pack_scene(Scene()).instances) == 0
    mesh = triangle()
    mesh.faces[0].attrs['color'] = (1, 0, 0)
    packed = pack_scene(Scene(groups=[Group(mesh)]))
    np.testing.assert_array_equal(packed.vertices['color'], [[255, 0, 0, 255]]*3)


def test_prototype_offsets():
    packed = pack_scene(Scene(groups=[Group(triangle()), Group(triangle())]))
    assert packed.commands['first'].tolist() == [0, 3]
    assert packed.commands['base'].tolist() == [0, 3]
    assert packed.commands['start'].tolist() == [0, 1]
    assert packed.indices.tolist() == [0, 1, 2, 0, 1, 2]
