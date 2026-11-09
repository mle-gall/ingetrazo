import os, sys, time, faulthandler
from pathlib import Path
from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication
root = Path.cwd()/'.r2-tmp/runtime'
root.mkdir(parents=True, exist_ok=True)
QStandardPaths.writableLocation = staticmethod(lambda kind: str(root / str(kind.value)))
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root))
os.environ['INGETRAZO_TEXTURE_CACHE'] = str(root/'textures')
app = QApplication([])
app.setOrganizationName('R2cBench')
app.setApplicationName('R2cBench')
from core import general_settings
general_settings.set_value('autosave','0')
if os.environ.get('R2C_BASELINE') == '1':
    import types
    module = types.ModuleType('views.main_window')
    module.__file__ = str(Path.cwd()/'views/main_window.py')
    sys.modules[module.__name__] = module
    exec(compile(Path('.r2-tmp/baseline_main_window.py').read_text(), module.__file__, 'exec'), module.__dict__)
from core import paths
paths.user_log_dir = lambda: root
from views.main_window import MainWindow
from views.main_window import igz_format
original = igz_format.load_into
loaded = None
load_depth = 0
def load(*args, **kw):
    global loaded, load_depth
    load_depth += 1
    try:
        result = original(*args, **kw)
    finally:
        load_depth -= 1
    if load_depth == 0:
        loaded = time.perf_counter()
        print('DOCUMENT_LOADED', loaded, flush=True)
        window.raise_()
        window.activateWindow()
    return result
igz_format.load_into = load
window = MainWindow(defer_extensions=True)
window.resize(1100,800)
window.show()
if os.environ.get('R2C_DETAIL') == '1':
    for method in ('_apply_camera_home', '_remember_recent', '_sync_style_menu', '_sync_section_menu', '_update_title'):
        original_method = getattr(window, method)
        def timed(*args, _fn=original_method, _name=method, **kwargs):
            start = time.perf_counter()
            result = _fn(*args, **kwargs)
            if loaded is not None:
                print('PHASE', _name, time.perf_counter()-start, flush=True)
            return result
        setattr(window, method, timed)
def frame(*args):
    display = getattr(window._doc, 'stand_in', None)
    if display is not None and not getattr(display, '_bench_loaded_scene', False):
        return
    if display is None and window.viewport._edges_version != window.viewport.scene.version:
        return
    if loaded is not None:
        print('FIRST_MODEL_FRAME', time.perf_counter()-loaded, flush=True)
        if display is not None:
            print('INSTANCES', len(display.packed.instances), 'PACK', display.build_seconds, display.packed.timings, 'UPLOAD', display.upload_seconds, flush=True)
        os._exit(0)
def observe(display):
    original_scene = display.set_scene
    def scene(*args):
        result = original_scene(*args)
        if loaded is not None:
            display._bench_loaded_scene = True
            print('RESIDENT_LOADED', len(display.packed.instances), flush=True)
        return result
    display.set_scene = scene
    display.frameReady.connect(frame)
if getattr(window._doc,'stand_in',None):
    observe(window._doc.stand_in)
else:
    window.viewport.frameSwapped.connect(frame)
original_install = window._install_wgpu_display
def install(doc):
    original_install(doc)
    observe(doc.stand_in)
window._install_wgpu_display = install
original_wire = window._wire_viewport
def wire(vp):
    original_wire(vp)
    vp.frameSwapped.connect(frame)
window._wire_viewport = wire
faulthandler.dump_traceback_later(10, repeat=True)
QTimer.singleShot(500, lambda: window.open_path(Path('/Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz')))
app.exec()
faulthandler.cancel_dump_traceback_later()
os._exit(0)
