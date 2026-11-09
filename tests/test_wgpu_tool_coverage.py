"""The published coverage includes every built-in registry entry."""
from pathlib import Path
from tools.metal_coverage import registry, table
from views.wgpu_tools import TOOL_DISPATCH


def test_registry_and_published_coverage_agree():
    root = Path(__file__).resolve().parents[1]
    registered = registry(root)
    assert set(TOOL_DISPATCH) <= set(registered.values())
    assert {key for key, cls in registered.items() if cls not in TOOL_DISPATCH} == {
        'section'}
    rendered = table(root)
    for key in registered:
        assert f'| {key} |' in rendered
    document = (root / 'docs/performance-plan.md').read_text()
    assert '<!-- R3c-1 coverage -->\n' + rendered + '\n<!-- /R3c-1 coverage -->' in document
