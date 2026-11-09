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
from core.history import History
print('class_values', facets.values(index, 'class'), flush=True)
print('system_values', facets.values(index, 'system'), flush=True)
# Exercise the real placement path.
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
