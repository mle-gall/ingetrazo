# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Curve and identity regressions against SketchUp-authored fixtures."""
from collections import Counter
from pathlib import Path

import pytest
from PySide6.QtGui import QMatrix4x4

from core.scene import Scene
from formats.skp import apply_payload, load_skp
from formats.skp_openskp import _collect

DATA = Path(__file__).parent / "data"


def walk(groups):
    for group in groups:
        yield group
        yield from walk(group.children)


@pytest.mark.parametrize("year", [2017, 2021])
def test_real_arcs_keep_membership(year):
    scene = Scene()
    load_skp(scene, DATA / f"skp_arcs_{year}.skp")
    edges = [e for g in walk(scene.groups) for e in g.mesh.edges]
    counts = Counter(e.curve for e in edges if e.curve is not None)
    assert sorted(counts.values()) == [12, 12, 24]
    assert sum(e.curve is None for e in edges) == 1  # half-disc chord
    for g in walk(scene.groups):
        for edge in g.mesh.edges:
            if edge.curve is not None:
                assert len(g.mesh.curve_edges(edge)) == counts[edge.curve]


def test_nested_legacy_groups_keep_uids_and_repeated_imports_do_not_collide():
    first, second = Scene(), Scene()
    for scene in (first, second):
        load_skp(scene, DATA / "test_export.skp")
    before = [g.uid for g in walk(first.groups)]
    assert len(before) == 5
    assert before == [g.uid for g in walk(second.groups)]
    load_skp(first, DATA / "test_export.skp")
    after = [g.uid for g in walk(first.groups)]
    assert len(set(after)) == len(after) == 10
    assert after[:5] == before


def test_the_identity_namespace_is_the_file_name_not_its_definitions(tmp_path):
    """A file edited in SketchUp (a component added, one renamed) and
    imported again keeps its UIDs: the namespace comes from the file's name,
    not from a digest of its definition list."""
    import shutil
    from formats.skp import parse_skp
    src = DATA / "skp_instances_2021.skp"
    assert parse_skp(src)["identity_namespace"] == "skp_instances_2021"
    same_name = tmp_path / "SKP_Instances_2021.skp"      # case-folded
    shutil.copy(src, same_name)
    a, b = Scene(), Scene()
    load_skp(a, src)
    load_skp(b, same_name)
    assert [g.uid for g in walk(a.groups)] == [g.uid for g in walk(b.groups)]
    other_name = tmp_path / "renamed.skp"
    shutil.copy(src, other_name)
    c = Scene()
    load_skp(c, other_name)
    assert [g.uid for g in walk(a.groups)] != [g.uid for g in walk(c.groups)]


def test_flattened_copies_of_polyline_curves_get_separate_ids():
    from openskp.model import Definition, Edge, Vertex, Instance
    child = Definition(id=1, vertices={
        1: Vertex(1, 0, 0, 0), 2: Vertex(2, 10, 0, 0), 3: Vertex(3, 10, 10, 0)},
        edges={1: Edge(1, 1, 2, curve_id=42), 2: Edge(2, 2, 3, curve_id=42)})
    matrix = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]
    shifted = matrix.copy()
    shifted[9] = 30
    root = Definition(id=0, instances=[Instance(ref_idx=1, matrix=m)
                                       for m in (matrix, shifted)])
    curves, lines = [], []
    _collect(root, QMatrix4x4(), {1: child}, {}, [], 0, set(),
             loose_out=lines, curves_out=curves)
    scene = Scene()
    apply_payload(scene, {"groups": [{"faces": [], "soft_edges": [],
                                      "loose_edges": lines, "curves": curves}]})
    counts = Counter(e.curve for e in scene.groups[0].mesh.edges)
    assert sorted(counts.values()) == [2, 2]
    assert None not in counts


def test_placed_instances_use_pid_not_definition_or_position():
    from openskp.model import Definition, Edge, Vertex, Instance, SkpModel
    from formats.skp_openskp import _adapt
    child = Definition(id=1, name="line", vertices={1: Vertex(1, 0, 0, 0),
                       2: Vertex(2, 10, 0, 0)}, edges={1: Edge(1, 1, 2)})
    instances = [Instance(ref_idx=1, matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1])
                 for _ in range(2)]
    for ins, pid in zip(instances, (100, 101)):
        ins.persistent_id = pid
    model = SkpModel(definitions={1: child}, root=Definition(id=0, instances=instances))
    def uids():
        scene = Scene()
        apply_payload(scene, _adapt(model, "test"))
        return [g.uid for g in walk(scene.groups)]
    first = uids()
    assert len(first) == len(set(first)) == 2
    instances.reverse()
    instances[0].matrix[9] = 100
    assert uids() == first[::-1]


def test_modern_instance_ids_survive_the_raw_parser_bridge():
    from formats.skp_openskp import parse
    payload = parse(DATA / "skp_instances_2021.skp")
    assert payload["protos"][0]["instance_identities"] == [("73",), ("74",)]
    scenes = [Scene(), Scene()]
    for scene in scenes:
        load_skp(scene, DATA / "skp_instances_2021.skp")
    first = [g.uid for g in walk(scenes[0].groups)]
    assert len(first) == len(set(first)) == 2
    assert first == [g.uid for g in walk(scenes[1].groups)]


def test_missing_or_duplicate_ids_use_unique_fallbacks():
    payload = {"identity_namespace": "test", "groups": [
        {"faces": [], "soft_edges": [], "loose_edges": [((0, 0, 0), (1, 0, 0))],
         "identity": identity} for identity in [("1",), ("1",), None, None]]}
    scene = Scene()
    apply_payload(scene, payload)
    assert len({g.uid for g in scene.groups}) == 4


def test_shared_meshes_keep_curves_but_nested_placements_have_distinct_uids():
    from core.mesh import Mesh
    payload = {"identity_namespace": "nested", "protos": [
        {"faces": [], "children": [{"proto": 1, "xform": QMatrix4x4(),
                                    "identity": ("30",)}],
         "instances": [QMatrix4x4(), QMatrix4x4()],
         "instance_identities": [("10",), ("20",)]},
        {"faces": [], "soft_edges": [], "instances": [],
         "loose_edges": [((0, 0, 0), (1, 1, 0)), ((1, 1, 0), (2, 0, 0))],
         "curves": [[((0, 0, 0), (1, 1, 0)), ((1, 1, 0), (2, 0, 0))]]}]}
    scene = Scene()
    apply_payload(scene, payload)
    a, b = [g.children[0] for g in scene.groups]
    assert a.uid != b.uid
    assert a.mesh is b.mesh
    ids = {e.curve for e in a.mesh.edges}
    assert len(ids) == 1 and None not in ids
    assert Mesh.next_curve_id() not in ids
    again = Scene()
    apply_payload(again, payload)
    assert [g.uid for g in walk(scene.groups)] == [g.uid for g in walk(again.groups)]
