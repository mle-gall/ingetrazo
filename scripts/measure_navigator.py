"""Read-only Navigator timings on the owner's ride fixture (offscreen)."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core.scene import Scene
from core import facets
from formats.igz import load_into
app = QApplication([])
scene = Scene()
t = time.perf_counter()
load_into(scene, Path('/Users/legallmaxence/Desktop/space_exact/space_asbuilt_ride.igz'))
print('load', time.perf_counter()-t, flush=True)
t = time.perf_counter()
index = facets.build(scene)
print('index', time.perf_counter()-t, 'groups', len(index), flush=True)
print('records', sum(g.ifc is not None for g in index.groups.values()), flush=True)
for expr in [None, {'facet': 'class', 'eq': 'IfcColumn'}, {'text': '*launch*'}, {'all': [{'facet': 'kind:discipline', 'eq': 'S'}, {'facet': 'system', 'exists': True}]}]:
    t = time.perf_counter()
    uids = facets.evaluate(index, expr)
    print('evaluate', json.dumps(expr), time.perf_counter()-t, len(uids), flush=True)
from types import SimpleNamespace
from core.history import History
from views.navigator import NavigatorDock
vp = SimpleNamespace(scene=scene, history=History(scene), update=lambda: None)
from PySide6.QtWidgets import QMainWindow
window = QMainWindow()
window.viewport = vp
dock = NavigatorDock(window)
t = time.perf_counter()
dock.index = index
dock.refilter()
print('first_tree', time.perf_counter()-t, flush=True)
t = time.perf_counter()
dock.checked = {'class': {'IfcColumn'}}
dock.refilter()
print('filter_change', time.perf_counter()-t, flush=True)
t = time.perf_counter()
dock.isolate()
print('isolate_display_state', time.perf_counter()-t, flush=True)
print('class_values', facets.values(index, 'class'), flush=True)
print('system_values', facets.values(index, 'system'), flush=True)
# Exercise the real placement path as well as the dock's display-state action.
# Offscreen cannot establish GPU upload or frame latency.
from views.viewport import Viewport
from core.agent_facets import set_display
render_view = Viewport()
render_view.scene = scene
render_view.history = History(scene)
t = time.perf_counter()
set_display(render_view, {'text': '*launch*'}, 'tag')
print('isolate_launch_and_tint_state', time.perf_counter()-t, flush=True)
t = time.perf_counter()
placements = render_view._placements()
print('filtered_placement_proxies', time.perf_counter()-t, len(placements), flush=True)
render_view.close()
