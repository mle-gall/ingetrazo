"""Capture the same document and camera through GL and Metal, with bounded frames.

Run each model in an externally bounded subprocess (240 seconds). All outputs
and texture extraction stay in this worktree; source documents are read-only.
"""
import argparse
import math
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['INGETRAZO_RUST'] = '1'
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(Path('.look-tmp/textures').resolve())
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView

app = QApplication([])
out = Path('docs/benchmarks/wgpu-look-2026-11-09')
parser = argparse.ArgumentParser()
parser.add_argument('model', type=Path)
parser.add_argument('--mode', choices=('shaded', 'hidden_line', 'monochrome', 'wireframe', 'xray'))
parser.add_argument('--pitch', type=float)
parser.add_argument('--capture-only', action='store_true')
args = parser.parse_args()
source = args.model
label = source.stem
if args.mode:
    label += '-' + args.mode
if args.pitch is not None:
    label += '-pitch' + str(args.pitch)
scene = Scene()
load_into(scene, source)
if args.mode:
    scene.display_style.face_mode = args.mode
metal = WgpuView()
metal.resize(1000, 700)
metal.set_scene(scene)
if args.pitch is not None:
    metal.camera.pitch = math.radians(args.pitch)
gl = Viewport()
gl.resize(1000, 700)
gl.scene = scene
gl.camera = metal.camera
gl.show()
metal.source_viewport = gl
metal.show()


failed = []


def capture():
    try:
        metal.draw_frame()
        scale = metal.devicePixelRatioF()
        w, h = int(metal.width()*scale), int(metal.height()*scale)
        reference = gl.render_image(w, h, overlays=False)
        if reference is None:
            raise RuntimeError('GL render_image returned None')
        reference = reference.convertToFormat(QImage.Format_RGBA8888)
        data = bytes(metal.renderer.read_pixels())
        native = QImage(data, w, h, QImage.Format_RGBA8888).copy()
        reference.save(str(out / f'{label}-gl.png'))
        native.save(str(out / f'{label}-wgpu.png'))
        pair = QImage(w*2, h, QImage.Format_RGB32)
        painter = QPainter(pair)
        painter.drawImage(0, 0, reference)
        painter.drawImage(w, 0, native)
        painter.end()
        pair.save(str(out / f'{label}-comparison.png'))
        a = np.frombuffer(reference.constBits(), np.uint8).reshape(h, w, 4)
        b = np.frombuffer(native.constBits(), np.uint8).reshape(h, w, 4)
        result = {'scale': scale, 'size': [w,h], 'rgb_mae': float(np.abs(a[:,:,:3].astype(float)-b[:,:,:3]).mean()), 'frames': {}}
        for aa in (() if args.capture_only else (False, True)):
            metal.renderer.set_antialias(aa)
            for edges in (False, True):
                scene.display_style.edges = edges
                samples = []
                for i in range(45):
                    sample = metal.draw_frame()
                    if i >= 10:
                        samples.append(sample)
                result['frames'][f'msaa={aa},edges={edges}'] = {
                    'cpu_median_ms': float(np.median([s[0] for s in samples])),
                    'gpu_median_ms': float(np.median([s[1] for s in samples if s[1] is not None])),
                    'wall_median_ms': float(np.median([s[2] for s in samples]))}
        (out / f'{label}.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    except Exception as error:
        failed.append(str(error))
        import traceback
        traceback.print_exc()
    finally:
        metal.close()
        gl.close()
        app.quit()

QTimer.singleShot(1500, capture)
QTimer.singleShot(240000, app.quit)
app.exec()
if failed:
    raise SystemExit(1)
