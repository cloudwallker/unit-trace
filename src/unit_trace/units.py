"""An independent bounded unit grammar over fixed Pint unit objects."""

import math
import re

from pint import Unit, UnitRegistry
from pint.errors import DimensionalityError

from .models import CalculationError, Issue, input_error

SYMBOLS = {
    '1': None, 'm': 'meter', 'cm': 'centimeter', 'mm': 'millimeter',
    'um': 'micrometer', 'nm': 'nanometer', 'km': 'kilometer',
    's': 'second', 'ms': 'millisecond', 'us': 'microsecond', 'min': 'minute', 'h': 'hour',
    'kg': 'kilogram', 'g': 'gram', 'mg': 'milligram', 'L': 'liter', 'mL': 'milliliter',
    'mol': 'mole', 'mmol': 'millimole', 'A': 'ampere', 'mA': 'milliampere',
    'V': 'volt', 'mV': 'millivolt', 'ohm': 'ohm', 'kohm': 'kiloohm',
    'N': 'newton', 'Pa': 'pascal', 'kPa': 'kilopascal', 'MPa': 'megapascal',
    'J': 'joule', 'kJ': 'kilojoule', 'W': 'watt', 'mW': 'milliwatt',
    'Hz': 'hertz', 'rad': 'radian',
}
TOKEN = re.compile(r'\*\*|[A-Za-z]+|[0-9]+|[()*/+-]')


def make_registry() -> UnitRegistry:
    # Pint 0.25.2 resolves filename="" to its own default_en.txt, which imports
    # its sibling constants_en.txt. None disables the optional filesystem cache.
    registry = UnitRegistry(filename='', cache_folder=None, on_redefinition='raise',
                            autoconvert_offset_to_baseunit=False,
                            autoconvert_to_preferred=False, auto_reduce_dimensions=False,
                            force_ndarray=False, force_ndarray_like=False, case_sensitive=True)
    registry._unit_trace_units = {symbol: registry.Unit(name or 'dimensionless')
                                  for symbol, name in SYMBOLS.items()}
    return registry


def check_dimensions(unit: Unit) -> None:
    """Also used by the scalar engine after each future quantity operation."""
    if any(abs(power) > 24 for power in unit.dimensionality.values()):
        raise input_error('limit_exceeded', 'unit', 'Dimension exponent exceeds 24.')


def resolve_unit(text: str, registry: UnitRegistry) -> Unit:
    if text == 'cm²':
        raise input_error('unsupported_unit', 'unit', 'Use the ASCII spelling cm**2.')
    if text == 'μm':
        raise input_error('unsupported_unit', 'unit', 'Use the ASCII spelling um.')
    if not isinstance(text, str) or not text or not text.isascii() or any(c in text for c in '\r\n\x00'):
        raise input_error('unsupported_unit', 'unit', 'Expected single-line ASCII unit text.')
    if len(text) > 64:
        raise input_error('limit_exceeded', 'unit', 'Unit text exceeds 64 characters.')
    tokens = []
    position = 0
    while position < len(text):
        if text[position] in ' \t':
            position += 1
            continue
        match = TOKEN.match(text, position)
        if match is None:
            raise input_error('unsupported_unit', 'unit', 'Unsupported unit symbol or syntax.')
        tokens.append(match.group())
        if len(tokens) > 32:
            raise input_error('limit_exceeded', 'unit', 'Unit expression exceeds 32 tokens.')
        position = match.end()
    index = 0

    def error():
        return input_error('unsupported_unit', 'unit', 'Unsupported unit expression.')

    def peek():
        return tokens[index] if index < len(tokens) else None

    def atom(depth):
        nonlocal index
        token = peek()
        if token == '(':
            if depth >= 8:
                raise input_error('limit_exceeded', 'unit', 'Unit nesting exceeds eight levels.')
            index += 1
            value, powered = product(depth + 1)
            if peek() != ')':
                raise error()
            index += 1
        elif token in SYMBOLS:
            index += 1
            # These objects were built exclusively from fixed mapping names.
            value = registry._unit_trace_units[token]
            powered = False
            check_dimensions(value)
        else:
            raise error()
        if peek() == '**':
            if powered:
                raise input_error('unsupported_unit', 'unit', 'Nested unit powers are forbidden.')
            index += 1
            sign = 1
            if peek() in ('+', '-'):
                sign = -1 if peek() == '-' else 1
                index += 1
            exponent = peek()
            if exponent is None or not exponent.isdecimal():
                raise error()
            index += 1
            number = sign * int(exponent)
            if not -12 <= number <= 12:
                raise error()
            value = value ** number
            powered = True
            check_dimensions(value)
        return value, powered

    def product(depth):
        nonlocal index
        value, powered = atom(depth)
        while peek() in ('*', '/'):
            operation = peek()
            index += 1
            right, right_powered = atom(depth)
            value = value * right if operation == '*' else value / right
            powered = powered or right_powered
            check_dimensions(value)
        return value, powered

    value, _ = product(0)
    if index != len(tokens):
        raise error()
    return value


def conversion_factor(from_unit: str, to_unit: str) -> float:
    """A multiplicative factor independent of any input value, including zero."""
    registry = make_registry()
    source = resolve_unit(from_unit, registry)
    target = resolve_unit(to_unit, registry)
    return checked_factor(source, target, registry)


def calculation_error(code: str) -> CalculationError:
    messages = {'numeric_limit': 'Scalar result exceeds the supported numeric range.',
                'conversion_mismatch': 'Units cannot be converted.',
                'dimension_mismatch': 'Addition or subtraction requires matching dimensions.',
                'division_by_zero': 'Division by zero is forbidden.',
                'domain_error': 'Zero to the zero power is forbidden.',
                'limit_exceeded': 'Dimension exponent exceeds 24.'}
    return CalculationError(Issue(code + ':calculation', code, 'value', messages[code]))


def check_scalar(value: float, *, nonzero: bool = False) -> None:
    if (not math.isfinite(value) or (value != 0 and not 1e-100 <= abs(value) <= 1e100)
            or (nonzero and value == 0)):
        raise calculation_error('numeric_limit')


def checked_factor(source: Unit, target: Unit, registry: UnitRegistry) -> float:
    if source.dimensionality != target.dimensionality:
        raise calculation_error('conversion_mismatch')
    try:
        factor = float(registry.Quantity(1.0, source).to(target).magnitude)
    except (OverflowError, ZeroDivisionError):
        raise calculation_error('numeric_limit') from None
    except DimensionalityError:
        raise calculation_error('conversion_mismatch') from None
    check_scalar(factor, nonzero=True)
    return factor
