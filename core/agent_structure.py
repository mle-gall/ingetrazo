# SPDX-License-Identifier: GPL-3.0-or-later
"""Agents use the same filing transactions as the future structure panel."""
from collections import Counter
from copy import deepcopy

from core import bim_registry, structure
from core.agent_records import page
from core.history import CompoundCommand, SetRegistryCommand, SetStructureNodeCommand


class StructureTools:
    def _execute_structure(self, command):
        history = self._viewport.history
        if not isinstance(command, CompoundCommand) or command.commands:
            history.execute(command)
            if history.last_error or history.last_rejected:
                raise ValueError(history.last_error or history.last_rejected)

    def _tool_query_structure(self):
        scene = self._viewport.scene
        registry = bim_registry.get(scene)
        section = registry.get('structure', {})
        nodes = section.get('nodes', {})
        tree = structure.tree(registry)
        direct = Counter(k for _, _, _, k in structure._memberships(scene, registry) if k in nodes)
        counts = Counter()
        for k, count in direct.items():
            for ancestor in structure._lineage(registry, k):
                counts[ancestor] += count
        return dict(active=section.get('active'), roots=tree[None], nodes={
            key: {**node, 'children': tree[key], 'members': counts[key], 'direct_members': direct[key],
                  'resolved': structure.resolve(registry, key)} for key, node in nodes.items()})

    def _tool_set_structure(self, value=None, patch=None, force=False):
        if (value is None) == (patch is None) or type(force) is not bool:
            raise ValueError('Supply either value or patch and a boolean force')
        scene = self._viewport.scene
        registry = bim_registry.get(scene)
        section = deepcopy(registry.get('structure', {}))
        old = section.get('nodes', {}).copy()
        if patch is not None:
            if not isinstance(patch, dict):
                raise ValueError('patch must map keys to node edits or null')
            nodes = section.setdefault('nodes', {})
            for key, edit in patch.items():
                if edit is None:
                    nodes.pop(key, None)
                    if section.get('active') == key:
                        section.pop('active')
                elif isinstance(edit, dict):
                    nodes[key] = {**nodes.get(key, {}), **deepcopy(edit)}
                else:
                    raise ValueError('Node edit must be an object or null')
        else:
            section = deepcopy(value)
        registry['structure'] = section
        errors = bim_registry.validate(registry)
        if errors:
            raise ValueError('; '.join(errors))
        nodes = section.get('nodes', {})
        deleted = old.keys() - nodes.keys()
        targets = [g for g, src, _ in structure._placements(scene)
                   if not src and structure.node_of(g) in deleted]
        if targets and not force:
            raise ValueError('Cannot delete occupied nodes: ' + ', '.join(sorted({structure.node_of(g) for g in targets})))
        changed = [k for k in nodes if old.get(k) != nodes[k]]
        sync, report = structure._resync(scene, registry, changed)
        commands = [SetRegistryCommand(registry, refiled_uids=[g.uid for g in targets])]
        if targets:
            commands.append(SetStructureNodeCommand(targets, None))
        self._execute_structure(CompoundCommand([*commands, *sync.commands]))
        return dict(applied=True, changed=report, unfiled=[g.uid for g in targets])

    def _tool_file(self, uids, node):
        self._execute_structure(structure.file(self._viewport.scene, uids, node))
        return dict(applied=True, node=node, uids=list(dict.fromkeys(uids)))

    def _tool_query_unsorted(self, offset=0, limit=200):
        scene = self._viewport.scene
        wanted = set(structure.unsorted(scene))
        rows = [dict(uid=g.uid, name=g.name, node=structure.node_of(g),
                     tag=g.layer, **{'class': (g.ifc or {}).get('class')})
                for g, _, _ in structure._placements(scene) if g.uid in wanted]
        return page(rows, offset, limit)

    def _tool_bootstrap_structure(self, apply=False):
        if type(apply) is not bool:
            raise ValueError('apply must be boolean')
        scene = self._viewport.scene
        proposal = structure.bootstrap(scene, bim_registry.get(scene))
        if apply:
            self._execute_structure(structure.apply_bootstrap(scene, proposal))
        return {**proposal, 'applied': apply}
