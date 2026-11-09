"""P2 style contract and optional unshown-host Metal raster acceptance.

Default pytest uses Qt offscreen and skips native NSView tests. Run this file
with QT_QPA_PLATFORM=cocoa on macOS to execute GPU checks; no widget is shown.
"""
import importlib.util
import os
import sys
import numpy as np
import pytest
from core.scene import Scene
from views.wgpu_style import style_payload, sun_payload

HAS_RENDERER = importlib.util.find_spec("ingetrazo_render") is not None


def test_payload_defaults_and_hidden_controls():
    scene = Scene()
    p = style_payload(scene)
    assert p['material_opacity'] is True
    assert p['shadows'] is False
    assert p['group_selection_edges'] is True
    assert not p['show_hidden_geometry'] and not p['show_hidden_objects']
    scene.show_hidden_geometry = scene.show_hidden_objects = True
    scene.wgpu_material_opacity = True
    p = style_payload(scene)
    assert p['show_hidden_geometry'] and p['show_hidden_objects'] and p['material_opacity']


def test_sun_matches_gl_and_can_be_disabled(monkeypatch):
    from PySide6.QtGui import QVector3D
    from views.viewport import Viewport
    scene = Scene()
    scene.loose_mesh.add_face([QVector3D(0,0,0), QVector3D(1,0,0), QVector3D(0,1,1)])
    scene.shadows.enabled = True
    scene.shadows.hour = 12
    p = sun_payload(scene)
    view = Viewport(); view.scene = scene
    assert p['shadows']
    np.testing.assert_allclose(p['sun_direction'], view._sun_dir_now())
    assert len(p['shadow_matrix']) == 16
    assert sun_payload(scene, override=scene.display_style)['shadows']
    from core.style import Style
    assert not sun_payload(scene, override=Style(name='tecnico'))['shadows']
    monkeypatch.setenv('INGETRAZO_NO_SHADOWS','1')
    assert not sun_payload(scene)['shadows']
    view.close()


@pytest.mark.skipif(not HAS_RENDERER, reason='release ingetrazo_render required')
def test_native_api_available():
    from ingetrazo_render import Renderer
    for name in ('set_preview_mesh','set_face_marks','set_suppressed_faces',
                 'set_profile_exclusions','set_hidden_geometry'):
        assert hasattr(Renderer, name)


@pytest.fixture
def native():
    if not HAS_RENDERER or sys.platform != 'darwin' or os.environ.get('QT_QPA_PLATFORM') != 'cocoa':
        pytest.skip('Metal raster checks require release crate and unshown Cocoa NSView')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QMatrix4x4
    from ingetrazo_render import Renderer
    host = QWidget(); host.setAttribute(Qt.WA_DontShowOnScreen); host.resize(64,64)
    renderer = Renderer(int(host.winId()),64,64,1.)
    view=QMatrix4x4(); view.translate(0,0,-3)
    proj=QMatrix4x4(); proj.ortho(-1,1,-1,1,.1,10)
    renderer.set_camera(list(view.data()),list(proj.data()))
    renderer.set_antialias(False); renderer.set_edges(False)
    yield renderer
    del renderer
    host.close()


def synthetic_pack(alpha=64):
    from views.wgpu_scene import VERTEX, INSTANCE, COMMAND
    vertices=np.zeros(12,dtype=VERTEX)
    quad=np.array([[-.8,-.8,0],[.8,-.8,0],[.8,.8,0],[-.8,-.8,0],[.8,.8,0],[-.8,.8,0]],dtype=np.float32)
    vertices['pos'][:6]=quad; quad[:,2]=-.4; vertices['pos'][6:]=quad
    vertices['normal'][:,2]=1
    vertices['color'][:6]=[255,0,0,alpha]; vertices['color'][6:]=[0,0,255,255]
    indices=np.arange(12,dtype=np.uint32)
    bounds=np.array([[[-.8,-.8,-.4,0],[.8,.8,0,0]]],dtype=np.float32)
    commands=np.zeros(2,dtype=COMMAND); commands['count'][0]=12
    rows=np.zeros(1,dtype=INSTANCE); rows['world'][0]=np.eye(4,dtype=np.float32)
    return vertices,indices,bounds,commands,rows


def upload(renderer, alpha=64):
    v,i,b,c,r=synthetic_pack(alpha)
    renderer.set_scene(tuple(x.view(np.uint8).ravel() for x in (v,i,b,c)),r.view(np.uint8).ravel())
    return v,i,b,c,r


def capture(renderer):
    renderer.request_capture(); renderer.render(False)
    return np.frombuffer(bytes(renderer.take_capture()),np.uint8).reshape(64,64,4)


@pytest.mark.parametrize('aa',[False,True])
def test_material_alpha_blends_without_hiding_opaque_background(native,aa):
    upload(native,64); native.set_antialias(aa)
    native.set_style(dict(material_opacity=True,sky=False,edges=False,profiles=False))
    rgba=capture(native)
    mixed=rgba[32,32,:3].astype(int)
    if os.environ.get('P2_RASTER_OUTPUT'):
        from pathlib import Path
        from PySide6.QtGui import QImage
        path=Path(os.environ['P2_RASTER_OUTPUT']); path.mkdir(parents=True,exist_ok=True)
        QImage(rgba.data,64,64,QImage.Format_RGBA8888).copy().save(str(path/f'synthetic-alpha64-msaa-{aa}.png'))
    assert mixed[0]>70 and mixed[2]>120 and mixed[1]<5
    upload(native,255)
    opaque=capture(native)[32,32,:3].astype(int)
    assert opaque[0]>180 and opaque[2]<5
    assert mixed[0]<opaque[0]
    # An opaque front face hides translucent geometry behind it.
    v,i,b,c,r=synthetic_pack(64)
    v['pos'][:6,2]=-.8
    b[0,0,2]=-.8
    native.set_scene(tuple(x.view(np.uint8).ravel() for x in (v,i,b,c)),r.view(np.uint8).ravel())
    behind=capture(native)[32,32,:3]
    assert behind[0]<5 and behind[2]>180


def test_suppression_restores_and_rejects_invalid_ranges(native):
    upload(native,255); native.set_style(dict(material_opacity=True,sky=False))
    original=capture(native)
    native.set_suppressed_faces([(0,0,2)])
    hidden=capture(native)
    assert hidden[32,32,2]>150 and hidden[32,32,0]<5
    native.set_suppressed_faces([])
    np.testing.assert_array_equal(original,capture(native))
    with pytest.raises(ValueError): native.set_suppressed_faces([(0,3,2)])
    np.testing.assert_array_equal(original,capture(native))


@pytest.mark.parametrize('aa',[False,True])
def test_preview_and_face_marks_are_depth_tested(native,aa):
    v,*_=upload(native,255); native.set_antialias(aa)
    native.set_style(dict(sky=False,group_selection_edges=True))
    original=capture(native)
    empty=np.zeros(0,np.uint8)
    preview=v[:6].copy(); preview['pos'][:,2]=-.2; preview['color'][:]=[0,255,0,255]
    native.set_preview_mesh(preview.view(np.uint8).ravel(),empty)
    np.testing.assert_array_equal(original,capture(native))
    preview['pos'][:,2]=.2
    native.set_preview_mesh(preview.view(np.uint8).ravel(),empty)
    assert capture(native)[32,32,1]>150
    native.set_preview_mesh(empty,empty)
    np.testing.assert_array_equal(original,capture(native))
    marks=v[:6].copy(); marks['color'][:]=[0,0,255,255]
    native.set_face_marks(marks.view(np.uint8).ravel())
    marked=capture(native)
    assert np.count_nonzero(marked[:,:,2]>original[:,:,2])>20
    native.set_face_marks(empty)
    np.testing.assert_array_equal(original,capture(native))


def test_shadow_toggle_and_invalid_payload(native):
    upload(native,255)
    native.set_style(dict(shadows=False))
    original=capture(native)
    with pytest.raises(ValueError): native.set_style(dict(shadows=True,sun_direction=(0,0,0)))
    native.set_style(dict(shadows=False))
    np.testing.assert_array_equal(original,capture(native))
    from PySide6.QtGui import QMatrix4x4
    matrix=QMatrix4x4(); matrix.ortho(-2,2,-2,2,-2,2)
    native.set_style(dict(shadows=True,sun_direction=(1,0,0.1),shadow_matrix=list(matrix.data())))
    shaded=capture(native)
    assert shaded[32,32,0]<original[32,32,0]
    native.set_style(dict(shadows=False))
    np.testing.assert_array_equal(original,capture(native))


def test_hidden_ranges_are_opt_in(native):
    v,i,b,c,r=upload(native,255)
    hidden=v[:6].copy();hidden['pos'][:,2]=.2;hidden['color'][:]=[0,255,0,255]
    commands=c[:1].copy();commands['count']=6
    edges=commands.copy();edges['count']=0
    native.set_hidden_geometry(hidden.view(np.uint8).ravel(),i[:6].view(np.uint8),commands.view(np.uint8),edges.view(np.uint8))
    native.set_style(dict(show_hidden_geometry=False,sky=False))
    original=capture(native)
    native.set_style(dict(show_hidden_geometry=True,sky=False))
    ghost=capture(native)
    assert np.count_nonzero(ghost[:,:,1]>original[:,:,1])>100
    native.set_style(dict(show_hidden_geometry=False,sky=False))
    np.testing.assert_array_equal(original,capture(native))


@pytest.mark.parametrize('aa',[False,True])
def test_partial_texture_alpha_and_billboard_cutout(native,aa):
    v,i,b,c,r=upload(native,255)
    native.set_antialias(aa)
    native.set_style(dict(material_opacity=True,sky=False,edges=False))
    table=np.zeros((25,4),np.uint32)
    table[0]=[0,1,12,0]
    for index in range(12):
        table[1+index*2]=np.array([.5,.5,.5,.5],np.float32).view(np.uint32)
        if index<6:table[2+index*2,1:3]=1
    native.set_materials(table.view(np.uint8).ravel())
    native.set_textures(1,1,2,[[255,255,255,255,255,0,0,80]])
    mixed=capture(native)[32,32,:3]
    assert mixed[0]>80 and mixed[2]>150
    # Same texture on face-me geometry has a hard 0.5 threshold.
    r['info'][0,2]=8
    native.update_instances([0],r.view(np.uint8).ravel())
    cutout=capture(native)[32,32,:3]
    assert cutout[0]<5 and cutout[2]>180


def audit_handoff():
    """Exercise P2 with synthetic P3 alpha/soft handoffs, without changing pack code.

    Usage: python tests/test_metal_parity_raster.py MODEL --capture-only
           --live-frame --audit-case CASE --output DIR
    Remaining arguments are forwarded unchanged to the established audit harness.
    """
    from pathlib import Path
    import runpy
    import views.wgpu_view as module
    from views.wgpu_scene import PackedScene
    original_pack = module.pack_scene
    original_upload = PackedScene.upload
    import views.wgpu_style as style_module
    original_style = style_module.style_payload

    def packed(scene, *args, **kwargs):
        result = original_pack(scene, *args, **kwargs)
        # Only these fixture prototypes receive synthetic effective opacity.
        seen = set()
        for row, group in enumerate(result.groups):
            name = getattr(group, 'name', '')
            alpha = {'Mirrored glass': 77, 'Translucent tag': 64}.get(name)
            if alpha is None:
                continue
            prototype = int(result.instances['info'][row,0])
            if prototype in seen:
                continue
            seen.add(prototype)
            cmd = result.commands[prototype]
            indices = result.indices[int(cmd['first']):int(cmd['first']+cmd['count'])]+int(cmd['base'])
            result.vertices['color'][indices,3] = alpha
        return result

    def upload_with_flags(self, renderer):
        original_upload(self, renderer)
        # This smooth fixture has a single loose prototype. P3's real handoff
        # should provide endpoint pairs while packing, without face realization.
        if 'smooth' in Path(sys.argv[1]).stem:
            from formats.igz import load_into
            source = Scene(); load_into(source, Path(sys.argv[1]))
            pairs = [value for edge in source.loose_mesh.edges if edge.soft
                     for point in (edge.a,edge.b) for value in point.toTuple()]
            renderer.set_profile_exclusions([(0,pairs)])

    def payload(scene, *args, **kwargs):
        p = original_style(scene, *args, **kwargs)
        p['material_opacity'] = True
        return p

    module.pack_scene = packed
    style_module.style_payload = payload
    PackedScene.upload = upload_with_flags
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/wgpu_look_compare.py'),run_name='__main__')


if __name__ == '__main__':
    audit_handoff()
