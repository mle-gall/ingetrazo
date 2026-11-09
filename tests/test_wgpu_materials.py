"""Material handoff tests require no window or GPU device."""
import numpy as np
from views.wgpu_scene import _source_arrays, _texture_array
from PySide6.QtGui import QVector3D, QImage, QColor
from core.mesh import Mesh


def mesh_with(attrs):
    mesh = Mesh()
    mesh.add_face([QVector3D(0,0,0), QVector3D(2,0,0), QVector3D(0,3,0)])
    mesh.faces[0].attrs.update(attrs)
    return mesh


def test_front_paint_back_default_and_mirrored_paint():
    own = {'color': (0.4,0.1,0.05)}
    front = _source_arrays(mesh_with(own))
    np.testing.assert_array_equal(front[6][1], [102,25,12,255])
    assert front[10][0,0] == 0
    both = _source_arrays(mesh_with({**own, 'back': True}))
    assert both[10][0,0] == int.from_bytes(bytes([102,25,12,255]), 'little')


def test_separate_back_color_and_container_precedence():
    own = {'color': (0.4,0.1,0.05), 'back': {'color': (0,1,0)}}
    arrays = _source_arrays(mesh_with(own), {'color': (0,0,1)})
    np.testing.assert_array_equal(arrays[6][1], [102,25,12,255])
    assert arrays[10][0,0] == 0xff00ff00
    inherited = _source_arrays(mesh_with({}), {'color': (0,0,1)})
    assert inherited[10][0,0] == 0xffff0000


def test_layer_color_replaces_explicit_face_material():
    arrays = _source_arrays(mesh_with({'color': (1,0,0), 'layer': 'tag'}),
                            {'by_layer': {'tag': (0,1,0)}, 'color': (0,0,1)})
    np.testing.assert_array_equal(arrays[6][1], [0,255,0,255])
    assert arrays[10][0,0] == 0xff00ff00


def test_front_and_back_affines_preserve_leaf_grain():
    tex = {'path': 'unused.png', 'uvw': [2,0,0,.5,0,3,0,-1]}
    other = {**tex, 'uvw': [0,0,4,2,1,1,0,0]}
    ids = {}
    arrays = _source_arrays(mesh_with({'texture': tex, 'back': {'texture': other}}),
                            {'texture': {**tex,'uvw': [0]*8}}, ids)
    np.testing.assert_array_equal(arrays[9][0], tex['uvw']+other['uvw'])
    assert arrays[10][0,1:].tolist() == [1,1]
    assert ids == {'unused.png': 1}


def test_array_flips_v_and_supplies_mips(tmp_path):
    image = QImage(2,2,QImage.Format_RGBA8888)
    image.fill(QColor('red'))
    image.setPixelColor(0,1,QColor('blue'))
    path = tmp_path/'tile.png'
    assert image.save(str(path))
    w,h,layers,levels = _texture_array({str(path):1})
    assert (w,h,layers) == (2,2,2)
    assert [len(v) for v in levels] == [32,8]
    assert levels[0][16:20] == bytes([0,0,255,255])
