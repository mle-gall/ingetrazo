"""Bounded, offscreen source-level event contracts and real glyph painters."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QVector3D as V,QColor
from PySide6.QtCore import QPointF
from views.viewport import Viewport
from views.wgpu_view import WgpuView
from views.wgpu_tools import NativeTools,TOOL_DISPATCH
from views.wgpu_overlay import rasterize,snap_glyph,Primitive
app=QApplication([])
out=Path(__file__).with_name('raw')
gl=Viewport();gl.resize(700,600)
kinds=['endpoint','midpoint','on_edge','on_face','intersection','center','axis','component_origin','tangent']
a=QImage(700,600,QImage.Format_RGBA8888);a.fill(QColor('#eeeeee'))
b=QImage(a)
painter=QPainter(a);painter.setRenderHint(QPainter.Antialiasing)
prims=[]
for i,kind in enumerate(kinds):
    y=45+i*60
    gl._world_to_pixel=lambda p:(p.x(),p.y())
    gl._clip_pixel_line=lambda a,b:(a,b)
    snap=NS(point=V(250,y,0),kind=kind,color=(.1,.65,.2),guide=(V(300,y,0),V(640,y,0)),guide_color=None,guides=[])
    gl._draw_snap_indicator(painter,snap)
    painter.setPen(QColor('black'));painter.drawText(15,y,kind)
    prims.extend([snap_glyph((250,y),kind,'#1aa633'),Primitive('polyline',((300,y),(640,y)),'#1aa633')])
painter.end()
over=rasterize(prims,700,600,1)
p=QPainter(b);p.drawImage(0,0,over)
for i,kind in enumerate(kinds):p.setPen(QColor('black'));p.drawText(15,45+i*60,kind)
p.end()
a.save(str(out/'glyphs-gl.png'));b.save(str(out/'glyphs-wgpu.png'))
v=WgpuView();v.source_viewport=gl
calls=[]
v.renderer=NS(pick_rect=lambda *args:calls.append(args) or [])
v.devicePixelRatioF=lambda:1.
v.rect_rows(10,20,100,200);v.rect_rows(100,200,10,20)
result={'dispatch':TOOL_DISPATCH,'section_dispatched':'SectionPlaneTool' in TOOL_DISPATCH,
'box_direction_arguments':calls,'box_directions_identical':calls[0]==calls[1],
'pick_edge_any':v.tools.pick_edge_any(100,100),'pick_guide':v.tools.pick_guide(100,100),
'pick_axis':v.tools.pick_axis(100,100),'pick_section_plane':v.tools.pick_section_plane(100,100),
'pick_image_plane':v.tools.pick_image_plane(100,100),'accept_drops_gl':gl.acceptDrops(),'accept_drops_metal':v.acceptDrops()}
(out/'behavior-probe.json').write_text(json.dumps(result,indent=2))
v.renderer=None;v.close();gl.close()
print(json.dumps(result))
