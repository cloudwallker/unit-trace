"""Numerical dependency changes through the union of the old and new DAGs."""

from .graph import build_graph
from .models import ChangeSet, Formula, Project


def _signature(node):
    if isinstance(node, Formula):
        return ('formula', node.expression, node.output_unit)
    return ('variable', node.value, node.unit)


def compare_projects(current: Project, previous: Project | None) -> ChangeSet:
    new_graph = build_graph(current)
    if previous is None:
        return ChangeSet((), (), ())
    old_graph = build_graph(previous)
    current_nodes = {n.id: n for n in (*current.variables, *current.formulas)}
    previous_nodes = {n.id: n for n in (*previous.variables, *previous.formulas)}
    removed = tuple(i for i in previous_nodes if i not in current_nodes)
    changed = tuple(i for i, n in current_nodes.items()
                    if i not in previous_nodes or _signature(n) != _signature(previous_nodes[i])) + removed
    affected = set(changed)
    pending = list(changed)
    while pending:
        identifier = pending.pop()
        successors = (*new_graph.dependants.get(identifier, ()), *old_graph.dependants.get(identifier, ()))
        for successor in successors:
            if successor not in affected:
                affected.add(successor)
                pending.append(successor)
    return ChangeSet(changed, tuple(i for i in current_nodes if i in affected), removed)
