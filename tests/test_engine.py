import math
import unittest

from unit_trace.validation import parse_project


def project(variables, formulas):
    return parse_project({'schemaVersion': 1, 'profile': 'unit-trace-scalar-v1',
                          'title': 'Synthetic experiment',
                          'variables': [{'id': i, 'label': i, 'value': v, 'unit': u}
                                        for i, v, u in variables],
                          'formulas': [{'id': i, 'label': i, 'expression': e,
                                        **({'outputUnit': u} if u else {})}
                                       for i, e, u in formulas]})


def nodes(report):
    return {n.id: n for n in report.nodes}


class TraceTests(unittest.TestCase):
    def close(self, value, expected):
        self.assertTrue(math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-15),
                        (value, expected))

    def test_flow_and_conversion(self):
        from unit_trace.engine import evaluate_project, convert_input
        from unit_trace.units import conversion_factor
        p = project([('width', '2', 'cm'), ('height', '3', 'cm'), ('speed', '50', 'cm/s')],
                    [('area', 'width * height', 'cm**2'), ('flow', 'area * speed', 'm**3/s')])
        r = nodes(evaluate_project(p))
        self.close(r['area'].quantity.value, 6)
        self.close(r['flow'].quantity.value, .0003)
        data = p.to_json()
        data['formulas'][0]['outputUnit'] = 'm**2'
        r = nodes(evaluate_project(parse_project(data)))
        self.close(r['area'].quantity.value, .0006)
        self.close(r['area'].conversions[-1].factor, .0001)
        self.close(r['flow'].quantity.value, .0003)
        self.close(convert_input('0', 'cm', 'm').value, 0)
        self.close(conversion_factor('cm', 'm'), .01)
        r = nodes(evaluate_project(project([('a', '1', 'm'), ('b', '1', 'cm')],
                                          [('sum', 'a + b', None)])))
        self.close(r['sum'].quantity.value, 1.01)
        self.close(r['sum'].traces[0].conversions[0].factor, .01)
        self.assertEqual(r['sum'].traces[0].symbolic, 'a + b')
        self.assertIn('centimeter', r['sum'].traces[0].substitution)

    def test_inner_error_and_independent_roots(self):
        from unit_trace.engine import evaluate_project
        p = project([('width', '2', 'cm'), ('height', '3', 'cm'), ('speed', '50', 'cm/s')],
                    [('bad', 'speed * (width**2 + height)', None), ('child', 'bad * 2', None),
                     ('other', 'width + speed', None), ('joined', 'child + other', None),
                     ('good', 'width * height', None)])
        report = evaluate_project(p)
        r = nodes(report)
        self.assertEqual([i.node_id for i in report.root_errors], ['bad', 'other'])
        self.assertEqual(report.first_error, r['bad'].error)
        issue = r['bad'].error
        self.assertEqual(issue.code, 'dimension_mismatch')
        self.assertEqual(p.formulas[0].expression[issue.span.start:issue.span.end], 'width**2 + height')
        self.assertEqual([t.operator for t in r['bad'].traces], ['**', '+'])
        self.assertEqual(len(r['bad'].traces[-1].operands), 2)
        self.assertIsNone(r['bad'].traces[-1].result)
        self.assertEqual(r['bad'].traces[-1].issue_id, issue.id)
        for identifier in ['child', 'joined']:
            self.assertEqual(r[identifier].status, 'blocked')
            self.assertIsNone(r[identifier].quantity)
            self.assertIsNone(r[identifier].error)
        self.assertEqual(r['child'].root_error_ids, (issue.id,))
        self.assertEqual(r['joined'].root_error_ids, tuple(i.id for i in report.root_errors))
        self.assertEqual(r['good'].status, 'ok')
        self.close(r['good'].quantity.value, 6)

    def test_numeric_errors(self):
        from unit_trace.engine import evaluate_project, convert_input
        from unit_trace.models import CalculationError
        cases = [('1 / 0', 'division_by_zero'), ('0**0', 'domain_error'),
                 ('0**-1', 'division_by_zero'), ('1e100 * 1e100', 'numeric_limit'),
                 ('1e-100 * 1e-100', 'numeric_limit'), ('1e-100**12', 'numeric_limit'),
                 ('1e100**12', 'numeric_limit'), ('1e100 / 1e-100', 'numeric_limit'),
                 ('1e-100 / 1e100', 'numeric_limit')]
        for expression, code in cases:
            with self.subTest(expression=expression):
                report = evaluate_project(project([], [('bad', expression, None), ('down', 'bad * 2', None)]))
                r = nodes(report)
                self.assertEqual(r['bad'].error.code, code)
                self.assertEqual(r['down'].status, 'blocked')
                self.assertIsNone(r['bad'].quantity)
        p = project([('length', '1', 'm')], [('a', 'length**12', None), ('b', 'a * a', None),
                                           ('c', 'b * length', None), ('d', 'c / length', None)])
        r = nodes(evaluate_project(p))
        self.assertEqual(r['b'].status, 'ok')
        self.assertEqual(r['c'].error.code, 'limit_exceeded')
        self.assertEqual(r['d'].status, 'blocked')
        for value, source, target in [('1e100', 'm', 'nm'), ('1e-100', 'nm', 'm'),
                                      ('0', 'nm**12', 'km**12')]:
            with self.subTest(value=value, source=source):
                with self.assertRaises(CalculationError) as caught:
                    convert_input(value, source, target)
                self.assertEqual(caught.exception.issue.code, 'numeric_limit')
        r = nodes(evaluate_project(project([], [('zero', '1 - 1', None), ('signed', '-2**+2', None)])))
        self.close(r['zero'].quantity.value, 0)
        self.close(r['signed'].quantity.value, -4)
        report = evaluate_project(project([('x', '0', '1'), ('length', '1', 'm')], [('bad', 'x + length', None)]))
        self.assertEqual(report.first_error.code, 'dimension_mismatch')
        p = project([('x','1e100','m'), ('y','1e100','nm')], [('bad','x + y',None)])
        self.assertEqual(evaluate_project(p).first_error.code, 'numeric_limit')
        p = project([('x','1e100','m')], [('bad','x','nm'), ('down','bad',None)])
        r = nodes(evaluate_project(p))
        self.assertEqual(r['bad'].error.code, 'numeric_limit')
        self.assertEqual(r['down'].status, 'blocked')

    def test_range_and_scale_are_not_dimension_errors(self):
        from unit_trace.engine import evaluate_project
        p = project([('time', '100', 'ms'), ('distance', '1', 'm')],
                    [('speed', 'distance / time', 'm/s'), ('down', 'speed * 2', None)])
        data = p.to_json()
        data['variables'][0]['unit'] = 's'
        r = nodes(evaluate_project(parse_project(data)))
        self.close(r['speed'].quantity.value, .01)
        self.assertTrue(all(n.status == 'ok' and not n.warnings for n in r.values()))
        data['formulas'][0]['expected'] = {'min': '9', 'max': '11', 'unit': 'm/s'}
        r = nodes(evaluate_project(parse_project(data)))
        self.assertEqual(r['speed'].status, 'warning')
        self.assertEqual(r['speed'].warnings[0].code, 'range_outside')
        self.assertEqual(r['speed'].conversions[-1].reason, 'range')
        self.assertEqual(r['down'].status, 'ok')
        data['formulas'][0]['expected']['unit'] = 'kg'
        r = nodes(evaluate_project(parse_project(data)))
        self.assertEqual(r['speed'].warnings[0].code, 'range_unit_mismatch')
        self.assertEqual(r['down'].status, 'ok')
        data['formulas'][0]['outputUnit'] = 'kg'
        r = nodes(evaluate_project(parse_project(data)))
        self.assertEqual(r['speed'].error.code, 'conversion_mismatch')
        self.assertEqual(r['speed'].error.field, 'formulas[0].outputUnit')
        self.assertEqual(r['down'].status, 'blocked')
        for value in ['9', '11']:
            data = project([('x', value, 'm')], [('copy', 'x', None)]).to_json()
            for item in [data['variables'][0], data['formulas'][0]]:
                item['expected'] = {'min': '9', 'max': '11', 'unit': 'm'}
            self.assertTrue(all(n.status == 'ok' for n in evaluate_project(parse_project(data)).nodes))

    def test_range_conversion_numeric_limit_is_a_warning(self):
        from unit_trace.engine import evaluate_project
        data = project([('x', '1e100', 'm')], [('down', 'x', None)]).to_json()
        data['variables'][0]['expected'] = {'min': '0', 'max': '1e100', 'unit': 'nm'}
        r = nodes(evaluate_project(parse_project(data)))
        self.assertEqual(r['x'].warnings[0].code, 'numeric_limit')
        self.assertEqual(r['down'].status, 'ok')
        self.assertIsNotNone(r['x'].quantity)

    def test_failed_result_retains_successful_operand_conversion(self):
        from unit_trace.engine import evaluate_project
        p = project([('a', '1e100', 'm'), ('b', '1e100', 'cm')], [('bad', 'a + b', None)])
        r = nodes(evaluate_project(p))['bad']
        self.assertEqual(r.error.code, 'numeric_limit')
        self.assertIsNone(r.traces[-1].result)
        self.assertEqual(r.traces[-1].operands[1].unit, 'centimeter')
        self.close(r.traces[-1].conversions[0].factor, .01)
        self.assertEqual(r.traces[-1].conversions[0].reason, 'addition')

    def test_failed_left_branch_stops_right_branch(self):
        from unit_trace.engine import evaluate_project
        p = project([('x', '1', 'm'), ('t', '1', 's')], [('bad', '(x + t) * (1 / 0)', None)])
        report = evaluate_project(p)
        r = nodes(report)['bad']
        self.assertEqual(r.error.code, 'dimension_mismatch')
        self.assertEqual([t.operator for t in r.traces], ['+'])
        self.assertEqual(r.traces[0].symbolic, 'x + t')
        self.assertIsNotNone(r.substitution)

    def test_range_numeric_limits_do_not_claim_a_checked_range(self):
        from unit_trace.engine import evaluate_project
        cases = [('1e100','m','mm'), ('1e-100','nm','m'), ('1e-100','nm**12','km**12')]
        for value, unit, expected_unit in cases:
            with self.subTest(value=value, unit=unit):
                data = project([('x', value, unit)], [('down', 'x', None)]).to_json()
                data['variables'][0]['expected'] = {'min':'0','max':'1e100','unit':expected_unit}
                report = evaluate_project(parse_project(data))
                r = nodes(report)
                self.assertIsNone(report.first_error)
                self.assertEqual(r['x'].status, 'warning')
                self.assertEqual(r['x'].warnings[0].code, 'numeric_limit')
                self.assertEqual(r['x'].warnings[0].field, 'variables[0].expected')
                self.assertIn('User range could not be checked', r['x'].warnings[0].message)
                self.assertEqual(r['x'].conversions, ())
                self.assertEqual(r['down'].status, 'ok')
                self.assertEqual(r['x'].quantity.value, float(value))


if __name__ == '__main__':
    unittest.main()
