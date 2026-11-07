"""Selected occurrences tint real edges, including nested shared meshes."""
import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V, QMatrix4x4
from core.mesh import Mesh
from core.group import Group
from tests.test_rendering_surface_regressions import viewport, pixels


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('hidden', [False, True])
def test_selected_occurrence_tints_its_interior_edge_only(viewport, nested, hidden):
    vp = viewport
    m = Mesh()
    a,b,c,d = V(-1,-1,0),V(1,-1,0),V(1,1,0),V(-1,1,0)
    m.add_face([a,b,c]);m.add_face([a,c,d])
    diagonal = next(e for e in m.edges if len(e.faces)==2)
    diagonal.soft = hidden
    selected = Group(m, 'selected')
    selected.xform = QMatrix4x4()
    sibling = Group(m, 'unselected shared copy')
    sibling.xform = QMatrix4x4();sibling.xform.translate(3,0,0)
    if nested:
        parent = Group(Mesh(), 'parent')
        parent.adopt([selected])
        selected = parent
    vp.scene.groups.extend([selected,sibling])
    vp.scene.show_axes = False
    vp.scene.show_hidden_geometry = hidden
    vp.scene.version += 1
    vp.camera.target = V(1.5,0,0)
    vp.camera.distance = 9
    vp.camera.pitch = 1.2
    vp.camera.yaw = -.8
    vp.scene.select([selected])
    data = pixels(vp.grabFramebuffer())
    mvp = vp.camera.projection_matrix()*vp.camera.view_matrix()
    def orange_near(p):
        q=mvp.map(p)
        x=int((q.x()+1)*data.shape[1]/2)
        y=int((1-q.y())*data.shape[0]/2)
        patch=data[max(0,y-10):y+11,max(0,x-10):x+11]
        return np.count_nonzero((patch[:,:,0]>190)&(patch[:,:,1]>60)&(patch[:,:,1]<160)&(patch[:,:,2]<90))
    assert orange_near(V(0,0,0)) > 3  # interior diagonal, not the bounding box
    assert orange_near(V(3,0,0)) == 0 # same mesh, different occurrence
    assert m is sibling.mesh


@pytest.mark.parametrize('instance', [False, True])
def test_selected_smooth_tube_tints_profiles(viewport, instance):
    from tests.test_viewport_smooth_shading import _cylinder
    vp = viewport
    g = Group(_cylinder(Mesh()), 'smooth rail')
    if instance:
        g.xform = QMatrix4x4()
    vp.scene.groups.append(g)
    vp.scene.show_hidden_geometry = False
    vp.scene.display_style.profiles = True
    vp.scene.version += 1
    vp.camera.target = V(0,0,1)
    vp.camera.distance = 5
    vp.camera.yaw, vp.camera.pitch = .7, .2
    vp.scene.select([g])
    vp.grabFramebuffer()
    assert vp._selected_profile_count >= 4
