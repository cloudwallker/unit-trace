"""Parse user expressions as bounded data; never execute their AST."""

import ast
import io
import tokenize

from .models import ParsedFormula, Span, input_error
from .validation import ID_PATTERN, NUMBER_PATTERN, validate_number

ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub)


def parse_formula(expression: str) -> ParsedFormula:
    if not isinstance(expression, str) or not expression.strip() or not expression.isascii() or '\n' in expression or '\r' in expression or '\x00' in expression:
        raise input_error('unsupported_syntax', 'expression', 'Expected a single-line ASCII expression.')
    if len(expression) > 512:
        raise input_error('limit_exceeded', 'expression', 'Expression exceeds 512 characters.')
    depth = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(expression).readline):
            if token.type == tokenize.COMMENT:
                raise input_error('unsupported_syntax', 'expression', 'Comments are outside the scalar expression grammar.')
            if token.type == tokenize.NUMBER:
                if len(token.string) > 24:
                    raise input_error('limit_exceeded', 'expression', 'Numeric token exceeds 24 characters.')
                if not NUMBER_PATTERN.fullmatch(token.string):
                    raise input_error('unsupported_syntax', 'expression', 'Only decimal real numbers are supported.')
                validate_number(token.string, 'expression')
            if token.type == tokenize.OP:
                if token.string in ('(', '[', '{'):
                    depth += 1
                    if depth > 24:
                        raise input_error('limit_exceeded', 'expression', 'Expression nesting exceeds 24 levels.')
                elif token.string in (')', ']', '}'):
                    depth -= 1
                elif token.string == '^':
                    raise input_error('unsupported_syntax', 'expression', 'Use ** for an integer power.')
    except (tokenize.TokenError, IndentationError):
        raise input_error('unsupported_syntax', 'expression', 'Malformed expression.') from None
    leading = len(expression) - len(expression.lstrip())
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise input_error('unsupported_syntax', 'expression', 'Malformed expression.') from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        raise input_error('limit_exceeded', 'expression', 'Expression exceeds 128 AST nodes.')
    for node in nodes:
        if hasattr(node, 'col_offset'):
            node.col_offset += leading
            node.end_col_offset += leading
    refs = []

    def visit(node: ast.AST, level: int) -> None:
        span = Span(node.col_offset, node.end_col_offset) if hasattr(node, 'col_offset') else None
        if level > 24:
            raise input_error('limit_exceeded', 'expression', 'AST exceeds 24 levels.', span=span)
        if not isinstance(node, ALLOWED):
            raise input_error('unsupported_syntax', 'expression', 'Unsupported expression construct.', span=span)
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise input_error('unsupported_syntax', 'expression', 'Only real numeric constants are supported.', span=span)
            # Token validation has already bounded precision and magnitude.
            node.value = float(node.value)
        if isinstance(node, ast.Name):
            if not ID_PATTERN.fullmatch(node.id):
                raise input_error('unsupported_syntax', 'expression', 'Invalid reference identifier.', span=span)
            if node.id not in refs:
                refs.append(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            sign = 1
            if isinstance(exponent, ast.UnaryOp) and isinstance(exponent.op, (ast.UAdd, ast.USub)):
                sign = -1 if isinstance(exponent.op, ast.USub) else 1
                exponent = exponent.operand
            # Inspect the original source token, before numeric constants become floats.
            text = expression[exponent.col_offset:exponent.end_col_offset] if isinstance(exponent, ast.Constant) else ''
            if not text.isascii() or not text.isdecimal() or not -12 <= sign * int(text) <= 12:
                raise input_error('unsupported_syntax', 'expression', 'Power exponent must be an integer literal from -12 to 12.', span=span)
            if any(isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow)
                   for child in ast.walk(node.left)):
                raise input_error('unsupported_syntax', 'expression', 'Nested powers are forbidden.', span=span)
        for child in ast.iter_child_nodes(node):
            visit(child, level + 1)

    visit(tree, 1)
    return ParsedFormula(expression, tree, tuple(refs))
