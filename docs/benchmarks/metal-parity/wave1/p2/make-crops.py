"""Crop identical GL/Metal rectangles; unshown Qt image operations only."""
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor
app=QApplication([])
root=Path(__file__).resolve().parent
out=root/'crops';out.mkdir(exist_ok=True)
cases={
 'synthetic-guides-only':(170,180,690,480),
 'alpha':(220,20,600,650),
 'synthetic-shadows':(170,180,690,480),
 'smooth':(220,20,600,650),
 'synthetic-selected-group':(170,180,690,480),
 'synthetic-xray-xray':(170,180,690,480),
 'synthetic-ao':(170,180,690,480),
 'pusher_car_rust':(435,285,330,190),
 'new-document':(220,20,600,650),
}
manifest=[]
for name,rect in cases.items():
 x,y,w,h=rect
 target=QImage(w*2,h+28,QImage.Format_RGB32);target.fill(QColor('white'))
 p=QPainter(target)
 for side,label in enumerate(('gl','wgpu')):
  image=QImage(str(root/f'{name}-{label}.png'))
  if image.isNull():raise RuntimeError(name)
  p.drawText(side*w+8,18,'OpenGL' if side==0 else 'Metal P2')
  p.drawImage(side*w,28,image.copy(x,y,w,h))
 p.end();path=out/f'{name}.png';target.save(str(path))
 manifest.append(dict(pair=path.name,crop_xywh=rect,bytes=path.stat().st_size))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
