"""Stable dependency graphs over a shared variable/formula namespace."""

import ast
import heapq

from .models import Graph, Issue, Project, ProjectValidationError, Span
from .syntax import parse_formula


def build_graph(project: Project) -> Graph:
    ids = [node.id for node in (*project.variables, *project.formulas)]
    positions = {}
    issues = []
    for kind, nodes in [('variables', project.variables), ('formulas', project.formulas)]:
        for index, node in enumerate(nodes):
            if node.id in positions:
                field = f'{kind}[{index}].id'
                issues.append(Issue(f'duplicate_id:{field}', 'duplicate_id', field,
                                    'Node identifier is duplicated.', (node.id,), node.id))
            else:
                positions[node.id] = len(positions)
    if issues:
        raise ProjectValidationError(tuple(issues))
    edges = []
    refs_by_id = {}
    for index, formula in enumerate(project.formulas):
        field = f'formulas[{index}].expression'
        try:
            parsed = parse_formula(formula.expression)
        except ProjectValidationError as error:
            issues.extend(Issue(f'{i.code}:{field}', i.code, field, i.message,
                                i.related_ids, formula.id, i.span) for i in error.issues)
            continue
        refs_by_id[formula.id] = parsed.refs
        for ref in parsed.refs:
            if ref not in positions:
                name = next(n for n in ast.walk(parsed.tree) if isinstance(n, ast.Name) and n.id == ref)
                issues.append(Issue(f'missing_reference:{formula.id}:{ref}', 'missing_reference', field,
                                    'Referenced node does not exist.', (ref,), formula.id,
                                    Span(name.col_offset, name.end_col_offset)))
            else:
                edges.append((ref, formula.id))
    if issues:
        raise ProjectValidationError(tuple(issues))
    dependants = {identifier: [] for identifier in ids}
    indegree = {identifier: 0 for identifier in ids}
    for source, target in edges:
        dependants[source].append(target)
        indegree[target] += 1
    ready = [positions[identifier] for identifier in ids if indegree[identifier] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        identifier = ids[heapq.heappop(ready)]
        order.append(identifier)
        for target in dependants[identifier]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, positions[target])
    if len(order) != len(ids):
        # Follow reference direction to show a closed path a -> b -> a.
        state = {}
        path = []

        def find_cycle(identifier):
            state[identifier] = 1
            path.append(identifier)
            for ref in refs_by_id.get(identifier, ()):
                if state.get(ref) == 1:
                    return tuple(path[path.index(ref):] + [ref])
                if state.get(ref, 0) == 0:
                    found = find_cycle(ref)
                    if found:
                        return found
            path.pop()
            state[identifier] = 2
            return None

        for identifier in ids:
            if state.get(identifier, 0) == 0:
                cycle = find_cycle(identifier)
                if cycle:
                    index = next(i for i, f in enumerate(project.formulas) if f.id == cycle[0])
                    field = f'formulas[{index}].expression'
                    raise ProjectValidationError((Issue(f'cycle:{cycle[0]}', 'cycle', field,
                                                        'Dependency graph contains a closed cycle.', cycle, cycle[0]),))
    return Graph(tuple(order), tuple(edges), {key: tuple(value) for key, value in dependants.items()})
