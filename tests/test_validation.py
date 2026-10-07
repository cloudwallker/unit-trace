import json
import unittest

from unit_trace.models import ProjectValidationError
from unit_trace.validation import load_json, parse_project


def project():
    return {'schemaVersion': 1, 'profile': 'unit-trace-scalar-v1', 'title': 'Experiment',
            'variables': [{'id': 'a', 'label': 'Length', 'value': '01.20', 'unit': 'cm'}],
            'formulas': []}


class ProtocolTests(unittest.TestCase):
    def reject(self, data, field=None):
        with self.assertRaises(ProjectValidationError) as caught:
            parse_project(data)
        self.assertTrue(caught.exception.issues)
        if field:
            self.assertIn(field, [i.field for i in caught.exception.issues])

    def test_number_text_is_preserved_and_optional_fields_omitted(self):
        parsed = parse_project(project())
        self.assertEqual(parsed.variables[0].value, '01.20')
        self.assertEqual(parsed.to_json(), project())

    def test_numeric_boundaries(self):
        for value in ['0', '-0', '1e-100', '-1e100', '.5', '+2.']:
            data = project()
            data['variables'][0]['value'] = value
            self.assertEqual(parse_project(data).variables[0].value, value)

    def test_invalid_numeric_values(self):
        for value in [True, False, None, 1, [], {}, 'NaN', 'Infinity', '1e101', '1e-101', '1e-999', '0x10', '1_000', '1' * 33]:
            with self.subTest(value=value):
                data = project()
                data['variables'][0]['value'] = value
                self.reject(data, 'variables[0].value')

    def test_counts_and_unknown_keys(self):
        data = project()
        data['variables'] = [{'id': f'v{i}', 'label': '', 'value': '1', 'unit': '1'} for i in range(81)]
        self.reject(data, 'variables')
        data = project()
        data['formulas'] = [{'id': f'f{i}', 'label': '', 'expression': 'a'} for i in range(21)]
        self.reject(data, 'formulas')
        for target in ['project', 'variable', 'formula', 'range']:
            data = project()
            data['formulas'] = [{'id': 'b', 'label': '', 'expression': 'a'}]
            data['variables'][0]['expected'] = {'min': '0', 'max': '2', 'unit': 'cm'}
            obj = {'project': data, 'variable': data['variables'][0], 'formula': data['formulas'][0], 'range': data['variables'][0]['expected']}[target]
            obj['unknown'] = 1
            self.reject(data)

    def test_range_and_field_locations(self):
        data = project()
        data['variables'][0]['expected'] = {'min': '2', 'max': '1', 'unit': 'cm'}
        self.reject(data, 'variables[0].expected')
        for invalid in ['for', 'True', 'a-b', '1a', 'a' * 33, 'é']:
            data = project()
            data['variables'][0]['id'] = invalid
            self.reject(data, 'variables[0].id')
        data = project()
        data['variables'][0]['label'] = 'x' * 81
        self.reject(data, 'variables[0].label')

    def test_schema_text_and_object_rejections(self):
        for key, value in [('schemaVersion', True), ('schemaVersion', 2), ('profile', 'other'), ('title', 'x'*121), ('title', '\x00'), ('title', '\ud800'), ('variables', {}), ('formulas', None)]:
            data = project()
            data[key] = value
            self.reject(data, key)
        self.reject([])

    def test_duplicate_json_and_nonfinite(self):
        for blob in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}', b'"\\ud800"', b'"\\u0000"', b'\xff', b'{']:
            with self.subTest(blob=blob):
                with self.assertRaises(ProjectValidationError):
                    load_json(blob)

    def test_json_depth_size_and_string_awareness(self):
        self.assertEqual(load_json(b'['*16+b'0'+b']'*16), [[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]])
        for blob in [b'['*17+b'0'+b']'*17, b' '*8388609]:
            with self.assertRaises(ProjectValidationError):
                load_json(blob)
        self.assertEqual(load_json(b'{"x":"[[[\\\"{\\\""}'), {'x': '[[["{"'})
        with self.assertRaises(ProjectValidationError):
            load_json(b'{} ', max_bytes=2)
        # Large supplied text is rejected rather than silently truncated.
        data = project()
        data['title'] = 'x' * 131073
        self.reject(data)

    def test_project_size_independent_of_bundle_limit(self):
        # Ensure the project cap is measured in UTF-8 bytes even when decoded already.
        data = project()
        data['variables'] = [{'id': f'v{i}', 'label': '😀'*80, 'value': '1'*32, 'unit': 'm'} for i in range(80)]
        data['formulas'] = [{'id': f'f{i}', 'label': '😀'*80, 'expression': ' '*500+'v0'} for i in range(20)]
        self.assertLess(len(json.dumps(data, ensure_ascii=False).encode()), 131072)
        self.assertEqual(len(parse_project(data).variables), 80)
