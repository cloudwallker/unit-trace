"""Left-to-right scalar AST evaluation; no user expression is executed."""

import ast

from .graph import build_graph
from .changes import compare_projects
from .models import (CalculationError, Conversion, EvaluationReport, Issue, NodeResult,
                     OperationTrace, Project, ProjectValidationError, QuantityView, Span)
from .profile import get_profile
from .serialization import project_hash
from .syntax import parse_formula
from .units import calculation_error, check_scalar, checked_factor, make_registry, resolve_unit
from .validation import validate_number

OPERATORS = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.Pow: '**',
             ast.UAdd: 'u+', ast.USub: 'u-'}


def quantity_view(quantity) -> QuantityView:
    value = float(quantity.magnitude)
    return QuantityView(value, format(value, '.17g'), str(quantity.units), str(quantity.dimensionality))


def checked_conversion(quantity, target, reason):
    factor = checked_factor(quantity.units, target, quantity._REGISTRY)
    try:
        result = quantity.to(target)
    except (OverflowError, ZeroDivisionError):
        raise calculation_error('numeric_limit') from None
    check_scalar(float(result.magnitude), nonzero=quantity.magnitude != 0)
    return result, Conversion(reason, str(quantity.units), str(target), factor)


def convert_input(value: str, from_unit: str, to_unit: str) -> QuantityView:
    registry = make_registry()
    quantity = registry.Quantity(validate_number(value), resolve_unit(from_unit, registry))
    result, _ = checked_conversion(quantity, resolve_unit(to_unit, registry), 'input')
    return quantity_view(result)


def _operation(op, operands, changes):
    a = operands[0]
    b = operands[1] if len(operands) == 2 else None
    if op in ('+', '-') and a.dimensionality != b.dimensionality:
        raise calculation_error('dimension_mismatch')
    if (op == '/' and b.magnitude == 0) or (op == '**' and a.magnitude == 0 and b.magnitude < 0):
        raise calculation_error('division_by_zero')
    if op == '**' and a.magnitude == 0 and b.magnitude == 0:
        raise calculation_error('domain_error')
    if op in ('+', '-'):
        b, conversion = checked_conversion(b, a.units, 'addition' if op == '+' else 'subtraction')
        changes.append(conversion)
    try:
        if op == '+': result = a + b
        elif op == '-': result = a - b
        elif op == '*': result = a * b
        elif op == '/': result = a / b
        elif op == '**': result = a ** int(b.magnitude)
        elif op == 'u+': result = +a
        else: result = -a
    except (OverflowError, ZeroDivisionError):
        raise calculation_error('numeric_limit') from None
    if any(abs(power) > 24 for power in result.dimensionality.values()):
        raise calculation_error('limit_exceeded')
    nonzero = op in ('*', '/', '**') and a.magnitude != 0 and (op == '**' or b.magnitude != 0)
    check_scalar(float(result.magnitude), nonzero=nonzero)
    return result, tuple(changes)


def _located(issue, identifier, field, span=None):
    suffix = f':{span.start}:{span.end}' if span else ''
    return Issue(f'{issue.code}:{identifier}:{field}{suffix}', issue.code, field,
                 issue.message, issue.related_ids, identifier, span)


def _resolve(text, registry, identifier, field):
    try:
        return resolve_unit(text, registry)
    except ProjectValidationError as error:
        raise ProjectValidationError(tuple(_located(i, identifier, field) for i in error.issues)) from None


def evaluate_project(project: Project, previous: Project | None = None) -> EvaluationReport:
    graph = build_graph(project)
    changes = compare_projects(project, previous)
    registry = make_registry()
    quantities, results_by_id = {}, {}
    results, roots = [], []
    variable_ids = {v.id for v in project.variables}
    by_id = {n.id: n for n in (*project.variables, *project.formulas)}
    fields = {n.id: f'{kind}[{index}]' for kind, collection in
              [('variables', project.variables), ('formulas', project.formulas)]
              for index, n in enumerate(collection)}
    units = {}
    # Unit syntax is structural input validation, before evaluating any branch.
    for identifier, node in by_id.items():
        text = node.unit if identifier in variable_ids else node.output_unit
        if text is not None:
            units[identifier] = _resolve(text, registry, identifier,
                                        fields[identifier] + ('.unit' if identifier in variable_ids else '.outputUnit'))
        if node.expected:
            units[(identifier, 'range')] = _resolve(node.expected.unit, registry, identifier,
                                                  fields[identifier] + '.expected.unit')
    for identifier in graph.order:
        node = by_id[identifier]
        kind = 'variable' if identifier in variable_ids else 'formula'
        symbolic = node.value if kind == 'variable' else node.expression
        traces, conversions = [], []
        error = None
        field = fields[identifier] + '.expression'
        parsed = parse_formula(node.expression) if kind == 'formula' else None
        if parsed:
            upstream = {root for ref in parsed.refs for root in results_by_id[ref].root_error_ids}
            blocked = tuple(root.id for root in roots if root.id in upstream)
            if blocked:
                result = NodeResult(identifier, kind, 'blocked', symbolic, None, None, root_error_ids=blocked)
                results.append(result)
                results_by_id[identifier] = result
                continue

        def visit(tree):
            if isinstance(tree, ast.Name):
                return quantities[tree.id]
            if isinstance(tree, ast.Constant):
                return registry.Quantity(tree.value, registry._unit_trace_units['1'])
            operands = [visit(tree.operand)] if isinstance(tree, ast.UnaryOp) else [visit(tree.left), visit(tree.right)]
            views = tuple(quantity_view(q) for q in operands)
            op = OPERATORS[type(tree.op)]
            span = Span(tree.col_offset, tree.end_col_offset)
            substitution = (' ' + op + ' ').join(q.roundtrip + ' ' + q.unit for q in views)
            if len(views) == 1:
                substitution = op[-1] + '(' + substitution + ')'
            successful_conversions = []
            try:
                quantity, changes = _operation(op, operands, successful_conversions)
            except CalculationError as caught:
                issue = _located(caught.issue, identifier, field, span)
                traces.append(OperationTrace(span, op, symbolic[span.start:span.end], substitution,
                                             views, None, tuple(successful_conversions), issue.id))
                raise CalculationError(issue) from None
            traces.append(OperationTrace(span, op, symbolic[span.start:span.end], substitution,
                                         views, quantity_view(quantity), changes, None))
            return quantity

        quantity = None
        substitution = None
        try:
            if kind == 'variable':
                quantity = registry.Quantity(validate_number(node.value), units[identifier])
                substitution = node.value + ' ' + node.unit
            else:
                quantity = visit(parsed.tree.body)
                substitution = traces[-1].substitution if traces else quantity_view(quantity).roundtrip + ' ' + str(quantity.units)
                if node.output_unit:
                    try:
                        quantity, conversion = checked_conversion(quantity, units[identifier], 'output')
                    except CalculationError as caught:
                        raise CalculationError(_located(caught.issue, identifier, fields[identifier] + '.outputUnit')) from None
                    conversions.append(conversion)
        except CalculationError as caught:
            error = caught.issue
            roots.append(error)
            quantity = None
            if traces:
                substitution = traces[-1].substitution
        warnings = []
        if quantity is not None:
            quantities[identifier] = quantity
            if node.expected:
                range_field = fields[identifier] + '.expected'
                target = units[(identifier, 'range')]
                if quantity.dimensionality != target.dimensionality:
                    warnings.append(Issue('range_unit_mismatch:' + identifier, 'range_unit_mismatch',
                                          range_field + '.unit', 'User range has incompatible dimensions.', node_id=identifier))
                else:
                    try:
                        ranged, conversion = checked_conversion(quantity, target, 'range')
                        conversions.append(conversion)
                        if not validate_number(node.expected.min) <= ranged.magnitude <= validate_number(node.expected.max):
                            warnings.append(Issue('range_outside:' + identifier, 'range_outside', range_field,
                                                  'Result is outside the user-provided range.', node_id=identifier))
                    except CalculationError as caught:
                        warning = Issue(caught.issue.id, caught.issue.code, range_field,
                                        'User range could not be checked because its conversion exceeds scalar limits.')
                        warnings.append(_located(warning, identifier, range_field))
        status = 'error' if error else ('warning' if warnings else 'ok')
        result = NodeResult(identifier, kind, status, symbolic, substitution,
                            quantity_view(quantity) if quantity is not None else None,
                            tuple(traces), tuple(conversions), tuple(warnings), error=error,
                            root_error_ids=(error.id,) if error else ())
        results.append(result)
        results_by_id[identifier] = result
    return EvaluationReport(1, get_profile(), project_hash(project),
                            graph.order, graph.edges, tuple(results), tuple(roots), roots[0] if roots else None,
                            changes.changed_ids, changes.affected_ids, changes.removed_ids)
