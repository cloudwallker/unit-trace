"""Shared scalar protocol models, with explicit public JSON mappings."""

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    def to_json(self) -> dict:
        return {'start': self.start, 'end': self.end}


@dataclass(frozen=True)
class Issue:
    id: str
    code: str
    field: str
    message: str
    related_ids: tuple[str, ...] = ()
    node_id: str | None = None
    span: Span | None = None

    def to_json(self) -> dict:
        data = {'id': self.id, 'code': self.code, 'field': self.field,
                'message': self.message, 'relatedIds': list(self.related_ids)}
        if self.node_id is not None:
            data['nodeId'] = self.node_id
        if self.span is not None:
            data['span'] = self.span.to_json()
        return data


class ProjectValidationError(ValueError):
    def __init__(self, issues: tuple[Issue, ...]):
        self.issues = tuple(issues)
        super().__init__('Invalid project input')


class CalculationError(ValueError):
    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__('Scalar calculation failed')


def input_error(code: str, field: str, message: str, *, node_id: str | None = None,
                span: Span | None = None, related_ids: tuple[str, ...] = ()) -> ProjectValidationError:
    return ProjectValidationError((Issue(f'{code}:{field}', code, field, message,
                                         related_ids, node_id, span),))


@dataclass(frozen=True)
class ExpectedRange:
    min: str
    max: str
    unit: str

    def to_json(self) -> dict:
        return {'min': self.min, 'max': self.max, 'unit': self.unit}


@dataclass(frozen=True)
class Variable:
    id: str
    label: str
    value: str
    unit: str
    expected: ExpectedRange | None = None

    def to_json(self) -> dict:
        data = {'id': self.id, 'label': self.label, 'value': self.value, 'unit': self.unit}
        if self.expected is not None:
            data['expected'] = self.expected.to_json()
        return data


@dataclass(frozen=True)
class Formula:
    id: str
    label: str
    expression: str
    output_unit: str | None = None
    expected: ExpectedRange | None = None

    def to_json(self) -> dict:
        data = {'id': self.id, 'label': self.label, 'expression': self.expression}
        if self.output_unit is not None:
            data['outputUnit'] = self.output_unit
        if self.expected is not None:
            data['expected'] = self.expected.to_json()
        return data


@dataclass(frozen=True)
class Project:
    schema_version: int
    profile: str
    title: str
    variables: tuple[Variable, ...]
    formulas: tuple[Formula, ...]

    def to_json(self) -> dict:
        return {'schemaVersion': self.schema_version, 'profile': self.profile, 'title': self.title,
                'variables': [v.to_json() for v in self.variables],
                'formulas': [f.to_json() for f in self.formulas]}


@dataclass(frozen=True)
class ParsedFormula:
    expression: str
    tree: ast.Expression
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Graph:
    order: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    dependants: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Profile:
    id: str
    schema_version: int
    python_version: str
    pint_version: str
    dependencies: dict[str, str]
    unit_whitelist_version: int
    definition_hashes: dict[str, str]

    def to_json(self) -> dict:
        return {'id': self.id, 'schemaVersion': self.schema_version,
                'pythonVersion': self.python_version, 'pintVersion': self.pint_version,
                'dependencies': dict(self.dependencies),
                'unitWhitelistVersion': self.unit_whitelist_version,
                'definitionHashes': dict(self.definition_hashes)}


@dataclass(frozen=True)
class QuantityView:
    value: float
    roundtrip: str
    unit: str
    dimensionality: str

    def to_json(self) -> dict:
        return {'value': self.value, 'roundtrip': self.roundtrip, 'unit': self.unit,
                'dimensionality': self.dimensionality}


@dataclass(frozen=True)
class Conversion:
    reason: str
    from_unit: str
    to_unit: str
    factor: float

    def to_json(self) -> dict:
        return {'reason': self.reason, 'fromUnit': self.from_unit,
                'toUnit': self.to_unit, 'factor': self.factor}


@dataclass(frozen=True)
class OperationTrace:
    span: Span
    operator: str
    symbolic: str
    substitution: str
    operands: tuple[QuantityView, ...]
    result: QuantityView | None
    conversions: tuple[Conversion, ...]
    issue_id: str | None

    def to_json(self) -> dict:
        return {'span': self.span.to_json(), 'operator': self.operator,
                'symbolic': self.symbolic, 'substitution': self.substitution,
                'operands': [q.to_json() for q in self.operands],
                'result': self.result.to_json() if self.result else None,
                'conversions': [c.to_json() for c in self.conversions], 'issueId': self.issue_id}


@dataclass(frozen=True)
class NodeResult:
    id: str
    kind: str
    status: str
    symbolic: str
    substitution: str | None
    quantity: QuantityView | None
    traces: tuple[OperationTrace, ...] = ()
    conversions: tuple[Conversion, ...] = ()
    warnings: tuple[Issue, ...] = ()
    error: Issue | None = None
    root_error_ids: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {'id': self.id, 'kind': self.kind, 'status': self.status,
                'symbolic': self.symbolic, 'substitution': self.substitution,
                'quantity': self.quantity.to_json() if self.quantity else None,
                'traces': [t.to_json() for t in self.traces],
                'conversions': [c.to_json() for c in self.conversions],
                'warnings': [w.to_json() for w in self.warnings],
                'error': self.error.to_json() if self.error else None,
                'rootErrorIds': list(self.root_error_ids)}


@dataclass(frozen=True)
class ChangeSet:
    changed_ids: tuple[str, ...]
    affected_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]

    def to_json(self) -> dict:
        return {'changedIds': list(self.changed_ids), 'affectedIds': list(self.affected_ids),
                'removedIds': list(self.removed_ids)}


@dataclass(frozen=True)
class EvaluationReport:
    schema_version: int
    profile: Profile
    project_hash: str
    topological_order: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    nodes: tuple[NodeResult, ...]
    root_errors: tuple[Issue, ...]
    first_error: Issue | None
    changed_ids: tuple[str, ...] = ()
    affected_ids: tuple[str, ...] = ()
    removed_ids: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {'schemaVersion': self.schema_version, 'profile': self.profile.to_json(),
                'projectHash': self.project_hash, 'topologicalOrder': list(self.topological_order),
                'edges': [{'from': a, 'to': b} for a, b in self.edges],
                'nodes': [n.to_json() for n in self.nodes],
                'rootErrors': [i.to_json() for i in self.root_errors],
                'firstError': self.first_error.to_json() if self.first_error else None,
                'changedIds': list(self.changed_ids), 'affectedIds': list(self.affected_ids),
                'removedIds': list(self.removed_ids)}


@dataclass(frozen=True)
class LoadedProject:
    project: Project
    source_profile: Profile | None
    requires_recompute_confirmation: bool
