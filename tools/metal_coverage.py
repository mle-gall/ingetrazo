"""Generate the Metal audit from the built-in MainWindow registry."""
import ast
from pathlib import Path
import re


def registry(root):
    tree = ast.parse((root / 'views/main_window.py').read_text())
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == '_tools' and isinstance(node.value, ast.Dict):
                result.update((key.value, value.func.id)
                              for key, value in zip(node.value.keys, node.value.values))
            if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute)
                    and target.value.attr == '_tools' and isinstance(target.slice, ast.Constant)
                    and isinstance(node.value, ast.Call)):
                result[target.slice.value] = node.value.func.id
    solids = ast.parse((root / 'tools/solid_tools.py').read_text())
    for node in solids.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOLID_TOOLS' for t in node.targets):
            result.update((pair.elts[0].value, pair.elts[1].id) for pair in node.value.elts)
    return result


def table(root=None):
    from views.wgpu_tools import TOOL_DISPATCH
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    sources = [p.read_text() for p in (root / 'tools').glob('*.py')]
    rows = ['| Registry key | Class | Metal status | GL hooks / preview dependencies |',
            '| --- | --- | --- | --- |']
    for key, cls in registry(root).items():
        status = 'native' if cls in TOOL_DISPATCH else 'inert with note'
        if key in ('section', 'texture_position'):
            status += ' — after the crate work'
        hooks = set()
        for source in sources:
            if 'class ' + cls + '(' not in source:
                continue
            hooks.update(re.findall(r'(?:viewport|vp)\.((?:pick_\w+|\w*preview\w*|_world_to_pixel|_pixel_to_ray))', source))
            if 'rubber_band_lines' in source:
                hooks.add('rubber_band_lines')
            if 'scale_box_state' in source:
                hooks.add('scale_box_state (screen handles)')
        rows.append(f"| {key} | {cls} | {status} | {', '.join(sorted(hooks)) or 'shared viewport / tool base'} |")
    return '\n'.join(rows)
