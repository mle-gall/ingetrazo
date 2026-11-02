# SPDX-License-Identifier: GPL-3.0-or-later
"""Explode in an edit context, including a component's nested placements."""
from core.history import Command, CommandRejected, ExplodeGroupCommand


def _contexts(scene, context):
    from core import outliner
    levels = list(scene._edit_stack)
    nodes = list(outliner.walk(scene.groups))
    result = [context]
    seen = {id(context)}
    for i, level in enumerate(levels):
        definition = level.get('definition')
        if definition is None:
            continue
        source = level['group']
        indices = []
        for next_level in levels[i + 1:]:
            child = next_level['group']
            indices.append(source.children.index(child))
            source = child
        for peer, _, _ in nodes:
            if peer is level['group'] or peer.mesh is not definition:
                continue
            target = peer
            for index in indices:
                if index >= len(target.children):
                    raise CommandRejected('Component copies have different structures; cannot explode safely')
                target = target.children[index]
            if id(target) not in seen:
                seen.add(id(target))
                result.append(target)
    return result


class ExplodeInContextCommand(Command):
    """One undo step for the active context and corresponding component copies.

    Container-only explosions change placement lists, never shared meshes.
    Dissolving geometry is also supported when the context has no other copy.
    Shared loose-geometry edits need definition-space mesh merging, so reject
    those before making any change instead of silently making a copy unique.
    """
    def __init__(self, context, groups):
        self.context = context
        self.groups = list(groups)
        self.operations = None

    def _prepare(self, scene):
        contexts = _contexts(scene, self.context)
        indices = [self.context.children.index(g) for g in self.groups]
        operations = []
        for ctx in contexts:
            for index in indices:
                if index >= len(ctx.children):
                    raise CommandRejected('Component copies have different structures; cannot explode safely')
                group = ctx.children[index]
                if len(contexts) > 1 and (group.mesh.faces or group.mesh.edges):
                    raise CommandRejected(
                        'Exploding loose geometry into a repeated component is not supported yet')
                operations.append((ctx, ExplodeGroupCommand(group)))
        return operations

    def _run(self, scene, context, command, undo=False):
        mesh, groups = scene.mesh, scene.groups
        scene.mesh, scene.groups = context.mesh, context.children
        try:
            (command.undo if undo else command.do)(scene)
        finally:
            scene.mesh, scene.groups = mesh, groups

    def do(self, scene):
        if self.operations is None:
            self.operations = self._prepare(scene)
        self.selection = set(scene.selection)
        applied = []
        selected = set()
        try:
            for context, command in self.operations:
                self._run(scene, context, command)
                applied.append((context, command))
                if context is self.context:
                    selected.update(context.children[command.index:command.index + len(command._lifted)])
        except Exception:
            for context, command in reversed(applied):
                self._run(scene, context, command, undo=True)
            scene.selection = set(self.selection)
            raise
        scene.selection = selected

    def undo(self, scene):
        for context, command in reversed(self.operations):
            self._run(scene, context, command, undo=True)
        scene.selection = set(self.selection)
