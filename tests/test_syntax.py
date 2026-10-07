import ast
from pathlib import Path
import tempfile
import unittest

from unit_trace.models import ProjectValidationError
from unit_trace.syntax import parse_formula


class ExpressionTests(unittest.TestCase):
    def test_ordered_refs_and_inner_source_span(self):
        parsed = parse_formula('a*(b+c)+b')
        self.assertEqual(parsed.refs, ('a', 'b', 'c'))
        inner = parsed.tree.body.left.right
        self.assertEqual(parsed.expression[inner.col_offset:inner.end_col_offset], 'b+c')

    def test_all_allowed_operations(self):
        for text in ['a+b-c*d/e', '-a + +b', 'x**-12', 'x**+12', 'x**0', '0.5*a', '.2e2', '  a + 1  ']:
            with self.subTest(text=text):
                self.assertIsInstance(parse_formula(text).tree, ast.Expression)

    def test_forbidden_syntax(self):
        for text in ['f()', 'x.y', 'x[0]', '[1]', '{}', '{x for x in y}', '[x for x in y]', 'True', 'False', 'None', '1j', "'x'", 'a//b', 'a%b', 'a^b', 'a<b', 'a and b', 'not a', 'a=1', '(a:=1)', 'lambda:a', 'a if b else c', 'a\nb', 'é', '2a', '0x10', '1_0']:
            with self.subTest(text=text):
                with self.assertRaises(ProjectValidationError):
                    parse_formula(text)

    def test_exponent_literals_limits_and_nesting(self):
        for text in ['x**13', 'x**-13', 'x**y', 'x**0.5', 'x**(1+1)', '(x**2)**2', 'x**2**2']:
            with self.subTest(text=text):
                with self.assertRaises(ProjectValidationError):
                    parse_formula(text)

    def test_parse_bounds_and_numbers(self):
        for text in ['a'*513, '('*25+'a'+')'*25, '+ '*25+'a', '1'*25, '1e101', '1e-101', '1e-999', '+'.join(['a']*65), '']:
            with self.subTest(text=text):
                with self.assertRaises(ProjectValidationError):
                    parse_formula(text)
        for text in ['0', '1e100', '1e-100']:
            parse_formula(text)

    def test_comments_are_outside_the_expression_grammar(self):
        with self.assertRaises(ProjectValidationError):
            parse_formula('a # ignored text')

    def test_malicious_call_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'marker'
            with self.assertRaises(ProjectValidationError):
                parse_formula(f"__import__('pathlib').Path({str(marker)!r}).touch()")
            self.assertFalse(marker.exists())
