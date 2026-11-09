"""Reproduce compact labelled GL-left / Metal-right evidence, no windows."""
import json
from pathlib import Path
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication
app=QApplication([])
root=Path(__file__).parent;out=root/'crops';out.mkdir(exist_ok=True)
manifest=[]
for gl in sorted((root/'raw').glob('*-gl.png')):
 stem=gl.name[:-7];metal=gl.with_name(stem+'-wgpu.png')
 if not metal.exists():continue
 if 'glyphs' in stem:x,y,w,h=0,0,700,680
 elif stem=='smooth':x,y,w,h=220,20,600,650
 else:x,y,w,h=170,180,690,480
 pair=QImage(w*2,h+24,QImage.Format_RGB32);pair.fill(QColor('white'))
 painter=QPainter(pair);painter.setPen(QColor('black'))
 for i,src in enumerate((gl,metal)):
  painter.drawImage(i*w,24,QImage(str(src)).copy(x,y,w,h))
  painter.drawText(i*w+8,17,'OpenGL' if i==0 else 'Metal')
 painter.end();path=out/(stem+'.png');pair.save(str(path))
 assert path.stat().st_size<=1000000,path
 manifest.append(dict(pair=path.name,gl=str(gl.relative_to(root)),metal=str(metal.relative_to(root)),crop_xywh=[x,y,w,h],bytes=path.stat().st_size))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2));print('pairs',len(manifest))
