"""Generate labelled evidence pairs with bounded sips crops (GL left)."""
import subprocess,json,tempfile
from pathlib import Path
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication
app=QApplication([])
root=Path(__file__).parent;out=root/'crops';out.mkdir(exist_ok=True)
manifest=[]
for gl in sorted((root/'raw').glob('*-gl.png')):
    stem=gl.name[:-7];metal=gl.with_name(stem+'-wgpu.png')
    if not metal.exists():continue
    if stem=='glyphs':x,y,w,h=0,0,700,600
    elif stem.startswith(('new-document','mesh-figure','smooth','alpha')):x,y,w,h=220,20,600,650
    elif stem.startswith('synthetic'):x,y,w,h=170,180,690,480
    else:x,y,w,h=200,80,650,580
    with tempfile.TemporaryDirectory() as td:
        ims=[]
        for src,name in [(gl,'gl'),(metal,'wgpu')]:
            dest=Path(td)/(name+'.png')
            subprocess.run(['sips','-c',str(h),str(w),'--cropOffset',str(y),str(x),str(src),'--out',str(dest)],timeout=15,check=True,capture_output=True)
            ims.append(QImage(str(dest)))
        pair=QImage(w*2,h+24,QImage.Format_RGB32);pair.fill(QColor('white'))
        painter=QPainter(pair);painter.setPen(QColor('black'))
        for i,im in enumerate(ims):painter.drawImage(i*w,24,im);painter.drawText(i*w+8,17,'OpenGL' if i==0 else 'Metal')
        painter.end();path=out/(stem+'.png');pair.save(str(path))
        subprocess.run(['sips','-Z','1400',str(path)],timeout=15,check=True,capture_output=True)
        assert path.stat().st_size<=1000000,path
        manifest.append(dict(pair=path.name,gl=str(gl.relative_to(root)),metal=str(metal.relative_to(root)),crop_xywh=[x,y,w,h],bytes=path.stat().st_size))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('pairs',len(manifest))
