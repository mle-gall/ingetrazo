"""Deterministic audit fixture; never modifies supplied models."""
from pathlib import Path
from PySide6.QtGui import QVector3D as V, QMatrix4x4, QImage, QColor
from core.scene import Scene
from core.mesh import Mesh
from core.group import Group
from core.section import SectionPlane
from core.guide import Guide
from core.dimension import Dimension
from core.textlabel import TextLabel
from core.image_plane import ImagePlane
from core.layers import Layer

def box(mesh, x, y, z, sx, sy, sz):
    corners = [V(x+dx*sx,y+dy*sy,z+dz*sz) for dz in (0,1) for dy in (0,1) for dx in (0,1)]
    for q in [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)]:
        mesh.add_face([corners[i] for i in reversed(q)])

def create():
    s=Scene()
    box(s.loose_mesh,-4,-3,-.2,8,6,.2)
    for i in range(3):
        m=Mesh(); box(m,0,0,0,1.3,1.3,2)
        for f in m.faces: f.attrs['color']=(.8,.25+i*.2,.15)
        xf=QMatrix4x4(); xf.translate(-2+i*2,0,0)
        g=Group(m,name=['Opaque','Translucent tag','Locked tag'][i]); g.xform=xf
        g.layer=[None,'Glass','Locked'][i]; s.groups.append(g)
    s.layers.extend([Layer('Glass',opacity=.25),Layer('Locked',locked=True)])
    s.guides=[Guide(V(0,0,2.5),V(1,0,0)),Guide(V(-2,-1,2.5),origin=V(-2,-1,0))]
    s.dimensions=[Dimension(V(-2,0,0),V(1.3,0,0),V(0,-2,0))]
    s.text_labels=[TextLabel(V(0,0,2),V(0,0,1),'Audit leader')]
    s.section_planes=[SectionPlane(V(0,0,1),V(0,0,1),active=False)]
    tex=Path(__file__).with_name('reference.png').resolve()
    im=QImage(64,64,QImage.Format_RGBA8888); im.fill(QColor('#cf35d2')); im.save(str(tex))
    s.image_planes=[ImagePlane(str(tex),V(-4,-3,.4),V(2,0,0),V(0,0,1.5),layer=None)]
    from core.text3d import make_text_group, text_params
    text=make_text_group(text_params('3D',height=.8,thickness=.15))
    xf=QMatrix4x4(); xf.translate(-3,-2,0); text.xform=xf; s.groups.append(text)
    hidden=Mesh();box(hidden,-3,-2,0,.7,.7,1)
    g=Group(hidden,name='Hidden');g.hidden=True;s.groups.append(g)
    # Hidden/soft edges and a hidden face on loose geometry.
    edge=s.loose_mesh.add_edge(V(-3,-2,2.5),V(3,-2,2.5));edge.hidden=True
    f=s.loose_mesh.add_face([V(-3,2,2),V(-2,2,2),V(-2,2,3)]);f.attrs['hidden']=True
    m=Mesh();box(m,0,0,0,.6,.6,1)
    for f in m.faces:f.attrs.update(color=(.2,.8,.3),opacity=.3)
    xf=QMatrix4x4();xf.translate(3,-2,0);xf.scale(-1,1,1.5)
    g=Group(m,name='Mirrored glass');g.xform=xf;s.groups.append(g)
    return s

def configure(s,case):
    if case.startswith('section'):
        for p in s.section_planes:p.active=True
        s.section_planes[0].fill={'pattern':'cross','spacing':.15}
    if case=='shadows':s.shadows.enabled=True;s.shadows.hour=10
    if case=='ao':s.display_style.ambient_occlusion=True;s.display_style.ao_distance=1
    if case=='hidden':s.show_hidden_geometry=True;s.show_hidden_objects=True
    if case=='by-tag':s.display_style.color_by_layer=True
    if case=='flat':s.display_style.sky=False;s.display_style.background=(.25,.45,.65)
    if case=='colors':s.display_style.front_color=(.8,.3,.2);s.display_style.back_color=(.2,.9,.3);s.display_style.edge_color=(.7,.1,.5)
    if case=='image-only':s.groups=[];s.loose_mesh=Mesh()
    if case=='edit':s.begin_group_edit(s.groups[0])
    if case=='guides-only':s.dimensions=[];s.text_labels=[]

if __name__=='__main__':
    from PySide6.QtWidgets import QApplication
    from formats.igz import save_scene
    app=QApplication([])
    save_scene(create(),Path(__file__).with_name('synthetic.igz'))


def live_setup(scene, gl, metal, case):
    from tools.select import SelectTool
    gl.flash_status=lambda *args: None
    gl.active_tool = SelectTool()
    if case in ('box-window','box-crossing','zoom-window'):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        a,b=QPointF(250,250),QPointF(650,550)
        if case=='box-crossing':a,b=b,a
        if case=='zoom-window':gl._zoom_box_active=True;gl._zoom_box_start=a;gl._zoom_box_cur=b
        else:gl._box_active=True;gl._box_start=a;gl._box_cur=b
        if case == 'zoom-window':
            gl.nav_mode = 'zoom_window'
        metal.tools.sync()
        QApplication.sendEvent(metal, QMouseEvent(QMouseEvent.MouseButtonPress,
            a, a, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(metal, QMouseEvent(QMouseEvent.MouseMove,
            b, b, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    if case == 'section-tool':
        from tools.section import SectionPlaneTool
        gl.active_tool=SectionPlaneTool();gl.active_tool.hover_point=V(0,0,2)
    if case == 'selected-group':scene.select([scene.groups[0]])
    if case == 'selected-face':
        # Select the visible slab top, not its obscured underside, so the
        # paired image actually exercises the depth-tested stipple pass.
        upward = [f for f in scene.loose_mesh.faces if f.normal().z() > .9]
        scene.select([max(upward, key=lambda f: max(p.z() for p in f.vertices))])
    if case == 'selected-edge':scene.select([scene.loose_mesh.edges[0]])
    if case == 'hover-face':gl._hover_entity=None  # Select intentionally suppresses face hover
    if case == 'hover-edge':gl.set_hover(next(e for e in scene.loose_mesh.edges if e.a.x()==4 and e.b.x()==4 and e.a.z()==0 and e.b.z()==0))
    if case == 'hover-group':
        gl._hover_entity=scene.groups[0]
        metal.hover_rows=metal.uid_rows.get(scene.groups[0].uid, [])


def extras():
    from formats.igz import save_scene
    from core.group import make_billboard_group
    import math
    root=Path(__file__).parent
    texture=Path('resources/components/person_billboard.png').resolve()
    image=QImage(str(texture))
    s=Scene(groups=[make_billboard_group(str(texture),1.75,'Default figure',image.width()/image.height())])
    save_scene(s,root/'new-document.igz')
    s.groups[0].billboard='mesh';save_scene(s,root/'mesh-figure.igz')
    s=Scene();m=s.loose_mesh
    # A cylinder whose shared side edges are soft, exercising corner normals.
    n=16
    for i in range(n):
        a,b=i*2*math.pi/n,(i+1)*2*math.pi/n
        m.add_face([V(math.cos(a),math.sin(a),0),V(math.cos(b),math.sin(b),0),V(math.cos(b),math.sin(b),2),V(math.cos(a),math.sin(a),2)])
    for e in m.edges:e.soft=True
    save_scene(s,root/'smooth.igz')
    tex=root/'alpha.png';im=QImage(64,64,QImage.Format_RGBA8888)
    for y in range(64):
        for x in range(64):im.setPixelColor(x,y,QColor(220,60,170,[0,80,160,255][x//16]))
    im.save(str(tex))
    s=Scene();box(s.loose_mesh,-1,-.3,0,2,.3,2)
    f=s.loose_mesh.add_face([V(-1,-.6,0),V(1,-.6,0),V(1,-.6,2),V(-1,-.6,2)])
    f.attrs['texture']={'path':str(tex.resolve()),'sw':2.,'sh':2.}
    save_scene(s,root/'alpha.igz')
