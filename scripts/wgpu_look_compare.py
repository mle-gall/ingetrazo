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
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from formats.igz import load_into
from views.viewport import Viewport
from views.wgpu_view import WgpuView

app = QApplication([])
out = Path('docs/benchmarks/wgpu-look-2026-11-09')
parser = argparse.ArgumentParser()
parser.add_argument('model', type=Path)
parser.add_argument('--edit-group', help='Exact name or slash-separated path; @nested selects first nested placement')
parser.add_argument('--edit-rest-mode', choices=('fade', 'hide', 'none'), default='fade')
parser.add_argument('--background', choices=('light', 'dark'))
parser.add_argument('--edit-benchmark', action='store_true')
parser.add_argument('--launch-section', action='store_true')
parser.add_argument('--mode', choices=('shaded', 'hidden_line', 'monochrome', 'wireframe', 'xray'))
parser.add_argument('--pitch', type=float)
parser.add_argument('--capture-only', action='store_true')
parser.add_argument('--output', type=Path, default=out)
parser.add_argument('--edges-off', action='store_true')
parser.add_argument('--profiles-off', action='store_true')
parser.add_argument('--back-edges', action='store_true')
parser.add_argument('--highlight', choices=('selected', 'hovered'))
parser.add_argument('--edge-width', type=float)
parser.add_argument('--audit-case', default='baseline')
parser.add_argument('--overlays', action='store_true')
parser.add_argument('--live-frame', action='store_true', help='Unshown interactive passes, including selection and overlays')
parser.add_argument('--measure-audit', action='store_true')
parser.add_argument('--p4-overlays', action='store_true',
                    help='Audit P4 helpers before P1 scheduling integration (capture-only live)')

args = parser.parse_args()
if args.capture_only and args.highlight:
    parser.error('Paired selection requires --live-frame --audit-case selected-group '
                 '(or hover-group); export paths omit interaction highlights')
if args.measure_audit and not (args.capture_only and args.live_frame):
    parser.error('--measure-audit requires --capture-only --live-frame')
if args.p4_overlays and not (args.capture_only and args.live_frame):
    parser.error("--p4-overlays requires --capture-only --live-frame")
out = args.output
out.mkdir(parents=True, exist_ok=True)
source = args.model
label = source.stem
if args.mode:
    label += '-' + args.mode
if args.pitch is not None:
    label += '-pitch' + str(args.pitch)
if args.profiles_off:
    label += '-profiles-off'
if args.back_edges:
    label += '-back-edges'
if args.edges_off:
    label += '-edges-off'
if args.edge_width is not None:
    label += '-width' + str(args.edge_width)
if args.highlight:
    label += '-' + args.highlight
scene = Scene()
load_start = time.perf_counter()
load_into(scene, source)
load_seconds = time.perf_counter() - load_start
if args.audit_case != 'baseline':
    sys.path.insert(0, str(Path('docs/benchmarks/metal-parity').resolve()))
    from fixture import configure
    configure(scene, args.audit_case)
    label += '-' + args.audit_case
if args.launch_section:
    scene.groups = [g for g in scene.groups if g.name == "Launch System | Launch_System.blend r3"]
    label += "-launch-section"
scene.display_style.face_mode = args.mode or 'textures'
if args.edges_off:
    scene.display_style.edges = False
if args.profiles_off:
    scene.display_style.profiles = False
if args.back_edges:
    scene.display_style.back_edges = True
edit_path = []
if args.edit_group:
    def paths(groups, parents=()):
        for group in groups:
            path = (*parents, group)
            yield path
            yield from paths(group.children, path)
    candidates = list(paths(scene.groups))
    chosen = next((p for p in candidates if
                   (args.edit_group == '@nested' and len(p) == 2) or
                   p[-1].name == args.edit_group or
                   '/'.join(g.name for g in p) == args.edit_group), None)
    if chosen is None:
        raise ValueError('Edit group not found')
    edit_path = [g.name for g in chosen]
    for group in chosen:
        scene.begin_group_edit(group)
    label += '-' + args.edit_rest_mode
if args.background:
    scene.display_style.background = ((.94, .94, .94) if args.background == 'light' else (.08, .08, .08))
    scene.display_style.sky = False
    label += '-' + args.background
metal = WgpuView()
if args.capture_only:
    metal.setAttribute(Qt.WA_DontShowOnScreen)
    # Captures never snap: avoid building a document-sized inference BVH.
    metal._prepare_inference = lambda: None

metal.resize(1000, 700)
metal.set_scene(scene)
if args.pitch is not None:
    metal.camera.pitch = math.radians(args.pitch)
camera_state = {k: QVector3D(v) if isinstance(v, QVector3D) else v
                for k, v in vars(metal.camera).items()}
gl = Viewport()
if args.capture_only:
    gl.setAttribute(Qt.WA_DontShowOnScreen)
gl._edit_rest_mode = "normal" if args.edit_rest_mode == "none" else args.edit_rest_mode
gl.resize(1000, 700)
gl.scene = scene
gl.camera = metal.camera
if args.capture_only:
    # Never map either widget. GL uses its ordinary paint pipeline on an
    # explicit offscreen context; Metal uses an unshown native host and FBOs.
    from PySide6.QtGui import QOpenGLContext, QOffscreenSurface
    context = QOpenGLContext()
    context.setFormat(gl.format())
    if not context.create():
        raise RuntimeError('offscreen GL context creation failed')
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    gl.context = lambda: context
    gl.makeCurrent = lambda: context.makeCurrent(surface)
    gl.doneCurrent = context.doneCurrent
    gl.makeCurrent()
    gl.initializeGL()
    metal.source_viewport = gl
    gl.camera.aspect = 1000 / 700
    if args.audit_case in ('parallel', 'section-parallel'):
        gl.camera.perspective = False
    if args.audit_case == 'two-point':
        gl.camera.two_point = True
    if args.edge_width is not None:
        gl._export_edge_px = args.edge_width
    warm_start = time.perf_counter()
    gl.render_image(1000, 700, overlays=False)
    gl_first_seconds = time.perf_counter() - warm_start
    timings = {}
    images = []
    if args.live_frame:
        sys.path.insert(0, str(Path('docs/benchmarks/metal-parity').resolve()))
        from fixture import live_setup
        live_setup(scene, gl, metal, args.audit_case)
    if args.p4_overlays:
        # Audit-only integration: production scheduling belongs to P1.
        import views.wgpu_overlay as p4_overlay
        from views.wgpu_annotations import draw_annotations, draw_tool_overlays
        from views.wgpu_annotations import composite_annotations
        from core.snap import SnapResult, COLOR_ENDPOINT
        from types import SimpleNamespace
        original_rasterize = p4_overlay.rasterize
        def glyph_gallery(painter, native):
            painter.fillRect(0, 0, 1000, 700, Qt.white)
            kinds = ('endpoint', 'midpoint', 'on_edge', 'on_face', 'intersection',
                     'center', 'axis', 'component_origin', 'tangent')
            project = lambda p: (p.x(), p.y())
            clip = lambda a, b: (a, b)
            reference = SimpleNamespace(_world_to_pixel=project, _clip_pixel_line=clip,
                                        _SNAP_LABELS=Viewport._SNAP_LABELS)
            for i, kind in enumerate(kinds):
                y = 40 + i * 70
                snap = SnapResult(kind=kind, point=QVector3D(200, y, 0),
                                  color=COLOR_ENDPOINT,
                                  guide=(QVector3D(400, y, 0), QVector3D(950, y, 0)))
                painter.setPen(Qt.black)
                painter.drawText(20, y, kind)
                if native:
                    p4_overlay.draw_snap_indicator(painter, snap, project, clip)
                else:
                    Viewport._draw_snap_indicator(reference, painter, snap)
        if args.audit_case == 'glyphs':
            gl._draw_overlay = lambda: None  # gallery is painted on readback below
        def p4_annotations(painter):
            if args.audit_case == 'export-overlays':
                return  # composite_annotations is exercised after capture below
            if args.audit_case == 'glyphs':
                glyph_gallery(painter, True)
                return
            draw_annotations(painter, scene, metal.camera, (1000, 700))
            draw_tool_overlays(painter, metal.tools)
        def p4_rasterize(primitives, width, height, scale, annotations=None):
            # Tool synchronization clears injected primitives during the first
            # frame; insert the test rectangle at the actual raster boundary.
            primitives = list(primitives)
            if args.audit_case in ('box-window', 'box-crossing', 'zoom-window'):
                a, b = (250, 250), (650, 550)
                if args.audit_case == 'box-crossing':
                    a, b = b, a
                primitives.append(p4_overlay.selection_rectangle(
                    a, b, zoom=args.audit_case == 'zoom-window'))
            return original_rasterize(primitives, width, height, scale, p4_annotations)
        p4_overlay.rasterize = p4_rasterize
        metal._paint_section_widgets = lambda image: None  # included above
        # A suppressed axis marker ensures the old scheduler runs on guides-only.
        metal.overlay_primitives = [p4_overlay.snap_glyph((0, 0), 'axis')]
    for name, view in [('gl', gl), ('wgpu', metal)]:
        start = time.perf_counter()
        if args.live_frame and name == 'gl':
            import views.viewport as viewport_module
            overlay = gl._draw_overlay
            gl._draw_overlay = lambda: None
            gl._fb_size = lambda: (1000, 700)
            gl.makeCurrent()
            gl.paintGL()
            result = gl._scene_fbo.toImage()
            gl._draw_overlay = overlay
            original_painter = viewport_module.QPainter
            class CapturePainter(original_painter):
                def __init__(self, target):
                    super().__init__(result if target is gl else target)
            viewport_module.QPainter = CapturePainter
            try:
                overlay()
            finally:
                viewport_module.QPainter = original_painter
        elif args.live_frame:
            # Initialize resident state without mapping the native host.
            import ingetrazo_render
            metal.renderer = ingetrazo_render.Renderer(int(metal.winId()), 1000, 700, 1.)
            metal.packed.upload(metal.renderer)
            metal._scene_dirty = False
            native_renderer = metal.renderer
            class OffscreenRenderer:
                def render(self):
                    native_renderer.request_capture()
                    return native_renderer.render(False)
                def __getattr__(self, name):
                    return getattr(native_renderer, name)
            metal.renderer = OffscreenRenderer()
            metal.devicePixelRatioF = lambda: 1.
            metal.draw_frame()
            rgba = bytes(native_renderer.take_capture())
            result = QImage(rgba, 1000, 700, QImage.Format_RGBA8888).copy()
        else:
            result = view.render_image(1000, 700, overlays=args.overlays)
        if args.p4_overlays and args.audit_case == 'glyphs' and name == 'gl':
            painter = QPainter(result)
            painter.setRenderHint(QPainter.Antialiasing)
            glyph_gallery(painter, False)
            painter.end()
        if args.p4_overlays and args.audit_case == 'export-overlays' and name == 'wgpu':
            result = composite_annotations(result, scene, metal.camera,
                                           logical_size=(1000, 700))
        timings[name] = time.perf_counter() - start
        if result is None or result.isNull():
            raise RuntimeError(name + ' returned no image')
        result.save(str(out / f'{label}-{name}.png'))
        images.append(result)
    pair = QImage(2000, 700, QImage.Format_RGB32)
    painter = QPainter(pair)
    for i, im in enumerate(images):
        painter.drawImage(i * 1000, 0, im)
    painter.end()
    pair.save(str(out / f'{label}-comparison.png'))
    import resource
    report = dict(load_seconds=load_seconds, capture_seconds=timings,
                  pack_seconds=metal.build_seconds, rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  resident_bytes=metal.renderer.gpu_memory, size=[1000, 700],
                  method=('unshown interactive passes, state injected' if args.live_frame
                          else 'unshown offscreen export; excludes interactive overlays'),
                  case=args.audit_case, overlays=args.overlays)
    report['live_frame'] = args.live_frame
    report['gl_first_capture_seconds'] = gl_first_seconds
    if args.measure_audit and args.live_frame:
        # Bounded samples. No presentation, no capture wait in measured frames.
        metal.renderer.render = lambda: native_renderer.render(False)
        report['offscreen_samples'] = []
        for i in range(8):
            metal.camera.yaw += .01
            start = time.perf_counter()
            frame = metal.draw_frame()
            before = time.perf_counter()
            row = metal.pick_row(500, 350)
            picked = time.perf_counter()
            metal.hover(500, 350)
            report['offscreen_samples'].append(dict(frame_wall_ms=(before-start)*1000,
                pick_ms=(picked-before)*1000, hover_ms=(time.perf_counter()-picked)*1000,
                row=row, frame=frame))
    (out / f'{label}.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    # Qt/GL resource destruction needs the offscreen context current.
    gl.makeCurrent()
    gl.release_gl_textures()
    metal.close()
    # Avoid processing queued widget paints or unrelated UI events on exit.
    os._exit(0)
gl.show()
metal.source_viewport = gl
metal.show()


failed = []


def capture():
    try:
        # Native windows can receive navigation during the startup delay.
        # Restore the fitted camera so paired captures stay comparable.
        vars(metal.camera).update(camera_state)
        metal.draw_frame()
        metal.renderer.set_highlight([], [])
        if args.highlight:
            # Instance highlight diagnostic; GL export intentionally omits its
            # selection overlay, so this pair is not selection parity evidence.
            metal.renderer.set_highlight([0] if args.highlight == 'selected' else [],
                                         [0] if args.highlight == 'hovered' else [])
        if args.edge_width is not None:
            from views.wgpu_style import style_payload
            payload = style_payload(scene)
            payload['edge_width'] = args.edge_width
            metal.renderer.set_style(payload)
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
        result = {'scale': scale, 'size': [w,h], 'rgb_mae': float(np.abs(a[:,:,:3].astype(float)-b[:,:,:3]).mean()), 'frames': {}, 'prototypes': len(metal.packed.bounds), 'vertices': len(metal.packed.vertices), 'material_bytes': metal.packed.materials.nbytes, 'resident_bytes': metal.renderer.gpu_memory}
        result['face_mode'] = scene.display_style.face_mode
        result['edit_rest_fade'] = gl.edit_rest_fade
        result['edit_rest_mode'] = gl.edit_rest_mode
        result['background'] = list(scene.display_style.background)
        result['edit_path'] = edit_path
        result['rest_write_ms'] = getattr(metal, 'rest_write_ms', None)
        result['rest_rows'] = int(np.count_nonzero(metal.packed.instances['info'][:, 2] & 64))
        if args.edit_benchmark:
            (out / f'{label}.json').write_text(json.dumps(result, indent=2))
            import subprocess
            result['uptime'] = subprocess.check_output(['uptime'], timeout=5, text=True).strip()
            result['edit_ab'] = {}
            for mode in ('normal', 'fade', 'normal', 'fade'):
                gl._edit_rest_mode = mode
                metal.sync_edit_context()
                samples = []
                for i in range(45):
                    metal.renderer.render(False)
                    if i >= 10:
                        samples.append(metal.renderer.last_timings()[:3])
                result['edit_ab'].setdefault(mode, []).append({'flag_write_ms': metal.rest_write_ms, 'median_ms': [float(np.median([s[j] for s in samples if s[j] is not None]))
                               if any(s[j] is not None for s in samples) else None for j in range(3)]})
                (out / f'{label}.json').write_text(json.dumps(result, indent=2))
        result['camera'] = {k: ([v.x(), v.y(), v.z()] if isinstance(v, QVector3D) else v)
                            for k, v in camera_state.items() if isinstance(v, (QVector3D, float, int, bool, str))}
        for aa in (() if args.capture_only else (False, True)):
            metal.renderer.set_antialias(aa)
            for edges in (False, True):
                scene.display_style.edges = edges
                samples = []
                stages = []
                for i in range(45):
                    sample = metal.draw_frame()
                    if i >= 10:
                        samples.append(sample)
                        stages.append(metal.renderer.frame_stage_timings())
                result['frames'][f'msaa={aa},edges={edges}'] = {
                    'stages_ms': dict(zip(('poll', 'acquire', 'encode', 'submit', 'present'), np.median(stages, axis=0).tolist())),
                    'cpu_median_ms': float(np.median([s[0] for s in samples])),
                    'gpu_median_ms': float(np.median([s[1] for s in samples if s[1] is not None])),
                    'wall_median_ms': float(np.median([s[2] for s in samples]))}
        if not args.capture_only:
            picks = []
            for _ in range(5):
                metal.draw_frame()
                begin = time.perf_counter()
                metal.renderer.pick(w//2, h//2)
                picks.append((time.perf_counter()-begin)*1000)
            result['pick_ms'] = picks
            offscreen = []
            for i in range(45):
                before = time.perf_counter()
                cpu, gpu = metal.renderer.render(False)
                wall = (time.perf_counter()-before)*1000
                if i >= 10:
                    offscreen.append((cpu, gpu, wall))
            result['offscreen_msaa_edges_on'] = {
                'cpu_median_ms': float(np.median([s[0] for s in offscreen])),
                'gpu_median_ms': float(np.median([s[1] for s in offscreen if s[1] is not None])),
                'wall_median_ms': float(np.median([s[2] for s in offscreen]))}
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
