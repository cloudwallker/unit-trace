import math
from pathlib import Path
import unittest

from unit_trace.engine import evaluate_project
from unit_trace.validation import load_json, parse_project
from tests.test_engine import nodes

TEMPLATES = Path(__file__).parents[1] / 'src/unit_trace/templates'
IDS = ('flow', 'density', 'spring', 'electric', 'energy', 'diffusion', 'concentration', 'pendulum')


class TemplateTests(unittest.TestCase):
    def test_eight_handwritten_experiments(self):
        for identifier in IDS:
            with self.subTest(template=identifier):
                directory = TEMPLATES / identifier
                expected = load_json((directory / 'expected.json').read_bytes())
                inputs = {variant: parse_project(load_json((directory / (variant + '.json')).read_bytes()))
                          for variant in ('normal', 'dimension', 'scale')}
                for p in inputs.values():
                    self.assertTrue(all(n.expected is None for n in (*p.variables, *p.formulas)))
                normal = evaluate_project(inputs['normal'])
                self.assertIsNone(normal.first_error)
                r = nodes(normal)
                for name, assertion in expected['normal'].items():
                    self.assertEqual(r[name].status, 'ok')
                    self.assertTrue(math.isclose(r[name].quantity.value, assertion['value'], rel_tol=1e-12, abs_tol=1e-15))
                    self.assertEqual(r[name].quantity.dimensionality, assertion['dimensionality'])
                bad = evaluate_project(inputs['dimension'])
                self.assertEqual(bad.first_error.node_id, expected['dimension']['root'])
                self.assertEqual(bad.first_error.code, 'dimension_mismatch')
                self.assertEqual(bad.first_error.span.to_json(), expected['dimension']['span'])
                self.assertEqual([n.id for n in bad.nodes if n.status == 'blocked'], expected['dimension']['blocked'])
                for n in bad.nodes:
                    if n.status == 'blocked':
                        self.assertIsNone(n.quantity)
                        self.assertEqual(n.root_error_ids, (bad.first_error.id,))
                scale = evaluate_project(inputs['scale'])
                self.assertTrue(all(n.status == 'ok' and not n.warnings for n in scale.nodes))
                target = expected['scale']['target']
                self.assertTrue(math.isclose(nodes(scale)[target].quantity.value, expected['scale']['value'], rel_tol=1e-12, abs_tol=1e-15))
                data = inputs['scale'].to_json()
                formula = next(f for f in data['formulas'] if f['id'] == target)
                normal_value = expected['normal'][target]['value']
                formula['expected'] = {'min': format(normal_value * .9, '.17g'),
                                       'max': format(normal_value * 1.1, '.17g'), 'unit': formula['outputUnit']}
                ranged = nodes(evaluate_project(parse_project(data)))
                self.assertEqual(ranged[target].warnings[0].code, 'range_outside')
                old = inputs['normal'].to_json()
                new = inputs['scale'].to_json()
                differences = [(a['id'], key) for a, b in zip(old['variables'], new['variables'])
                               for key in a if a[key] != b[key]]
                self.assertEqual(differences, [(expected['scale']['input'], 'unit')])
                self.assertEqual(old['formulas'], new['formulas'])
