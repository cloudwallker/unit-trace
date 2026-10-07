"""Strict, bounded JSON and scalar project protocol validation."""

import json
import keyword
import math
import re

from .models import ExpectedRange, Formula, Project, Variable, input_error

PROJECT_BYTES = 131072
NUMBER_PATTERN = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
ID_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}\Z')


def validate_number(text: object, field: str = 'value') -> float:
    if not isinstance(text, str) or not 1 <= len(text) <= 32 or not NUMBER_PATTERN.fullmatch(text):
        raise input_error('invalid_schema', field, 'Expected a decimal NumberText string.')
    number = float(text)
    # Lexically nonzero decimals must not silently become zero in binary64.
    mantissa = re.split('[eE]', text)[0]
    nonzero = any(c in '123456789' for c in mantissa)
    if not math.isfinite(number) or (nonzero and (number == 0 or not 1e-100 <= abs(number) <= 1e100)):
        raise input_error('numeric_limit', field, 'Number is outside the supported scalar range.')
    return number


def _valid_text(value: object, field: str, maximum: int, *, ascii_only: bool = False, nonempty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (nonempty and not value):
        raise input_error('invalid_schema', field, 'Text is missing or exceeds the field limit.')
    if '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise input_error('invalid_schema', field, 'Invalid Unicode text.')
    if ascii_only and (not value.isascii() or '\n' in value or '\r' in value):
        raise input_error('invalid_schema', field, 'Expected single-line ASCII text.')
    return value


def _check_decoded(value: object, field: str = '$', depth: int = 0) -> None:
    if isinstance(value, str):
        _valid_text(value, field, len(value))
    elif isinstance(value, float) and not math.isfinite(value):
        raise input_error('invalid_schema', field, 'Nonfinite JSON numbers are forbidden.')
    elif isinstance(value, (dict, list)):
        if depth >= 16:
            raise input_error('limit_exceeded', field, 'JSON nesting exceeds sixteen levels.')
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise input_error('invalid_schema', field, 'Object keys must be strings.')
                _valid_text(key, field, len(key))
                child_field = key if field == '$' else field + '.' + key
                _check_decoded(item, child_field, depth + 1)
        else:
            for index, item in enumerate(value):
                _check_decoded(item, f'{field}[{index}]', depth + 1)


def load_json(data: bytes, max_bytes: int = 8388608) -> object:
    if not isinstance(data, bytes) or type(max_bytes) is not int or max_bytes < 0:
        raise input_error('invalid_schema', '$', 'Expected bytes and a nonnegative byte limit.')
    if len(data) > max_bytes:
        raise input_error('limit_exceeded', '$', 'JSON exceeds the byte limit.')
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise input_error('invalid_schema', '$', 'Invalid UTF-8 JSON.') from None
    depth = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in '[{':
            depth += 1
            if depth > 16:
                raise input_error('limit_exceeded', '$', 'JSON nesting exceeds sixteen levels.')
        elif character in ']}':
            depth -= 1

    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise input_error('invalid_schema', '$', 'Duplicate JSON object key.')
            output[key] = value
        return output

    def constant(_):
        raise input_error('invalid_schema', '$', 'Nonfinite JSON constants are forbidden.')

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        from .models import ProjectValidationError
        if isinstance(error, ProjectValidationError):
            raise
        raise input_error('invalid_schema', '$', 'Malformed JSON.') from None
    _check_decoded(result)
    return result


def _object(data: object, required: set[str], optional: set[str], field: str) -> dict:
    if not isinstance(data, dict):
        raise input_error('invalid_schema', field, 'Expected an object.')
    if set(data) - required - optional or required - set(data):
        raise input_error('invalid_schema', field, 'Object has missing or unknown fields.')
    return data


def _unit(text: object, field: str) -> str:
    return _valid_text(text, field, 64, ascii_only=True, nonempty=True)


def _expected(data: object, field: str) -> ExpectedRange:
    obj = _object(data, {'min', 'max', 'unit'}, set(), field)
    minimum = validate_number(obj['min'], field + '.min')
    maximum = validate_number(obj['max'], field + '.max')
    if minimum > maximum:
        raise input_error('invalid_schema', field, 'Range minimum exceeds maximum.')
    return ExpectedRange(obj['min'], obj['max'], _unit(obj['unit'], field + '.unit'))


def parse_project(data: object) -> Project:
    _check_decoded(data)
    obj = _object(data, {'schemaVersion', 'profile', 'title', 'variables', 'formulas'}, set(), '$')
    if type(obj['schemaVersion']) is not int or obj['schemaVersion'] != 1:
        raise input_error('invalid_schema', 'schemaVersion', 'Unsupported schema version.')
    if obj['profile'] != 'unit-trace-scalar-v1':
        raise input_error('invalid_schema', 'profile', 'Unsupported scalar profile.')
    try:
        size = len(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError, OverflowError):
        raise input_error('invalid_schema', '$', 'Expected JSON-compatible project fields.') from None
    if size > PROJECT_BYTES:
        raise input_error('limit_exceeded', '$', 'Project exceeds 128 KiB.')
    title = _valid_text(obj['title'], 'title', 120)
    collections = []
    for name, limit in [('variables', 80), ('formulas', 20)]:
        values = obj[name]
        if not isinstance(values, list):
            raise input_error('invalid_schema', name, 'Expected a list.')
        if len(values) > limit:
            raise input_error('limit_exceeded', name, 'Node count exceeds the supported limit.')
        nodes = []
        for index, raw in enumerate(values):
            field = f'{name}[{index}]'
            required = {'id', 'label', 'value', 'unit'} if name == 'variables' else {'id', 'label', 'expression'}
            optional = {'expected'} if name == 'variables' else {'expected', 'outputUnit'}
            node = _object(raw, required, optional, field)
            identifier = node['id']
            if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier) or keyword.iskeyword(identifier):
                raise input_error('invalid_schema', field + '.id', 'Invalid node identifier.')
            label = _valid_text(node['label'], field + '.label', 80)
            expected = _expected(node['expected'], field + '.expected') if 'expected' in node else None
            if name == 'variables':
                validate_number(node['value'], field + '.value')
                nodes.append(Variable(identifier, label, node['value'], _unit(node['unit'], field + '.unit'), expected))
            else:
                expression = _valid_text(node['expression'], field + '.expression', 512, ascii_only=True, nonempty=True)
                output = _unit(node['outputUnit'], field + '.outputUnit') if 'outputUnit' in node else None
                nodes.append(Formula(identifier, label, expression, output, expected))
        collections.append(tuple(nodes))
    return Project(1, obj['profile'], title, collections[0], collections[1])
