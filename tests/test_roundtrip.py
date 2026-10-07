import copy
from dataclasses import replace
import hashlib
import json
import unittest

from unit_trace.engine import evaluate_project
from unit_trace.models import ProjectValidationError
from unit_trace.profile import get_profile
from unit_trace.validation import load_json
from tests.test_engine import nodes, project


class BundleTests(unittest.TestCase):
    def base(self):
        return project([('x', '02.00', 'cm')], [('area', 'x**2', 'm**2')])

    def test_same_profile_roundtrip_recomputes_and_retains_numbertext(self):
        from unit_trace.serialization import parse_bundle, serialize_bundle, project_hash
        p = self.base()
        report = evaluate_project(p)
        raw = serialize_bundle(p, report)
        loaded = parse_bundle(load_json(raw))
        self.assertEqual(loaded.project, p)
        self.assertFalse(loaded.requires_recompute_confirmation)
        self.assertEqual(loaded.source_profile, get_profile())
        self.assertEqual(evaluate_project(loaded.project).to_json(), report.to_json())
        self.assertEqual(loaded.project.variables[0].value, '02.00')
        self.assertEqual(project_hash(p), report.project_hash)
        standalone = parse_bundle(p.to_json())
        self.assertIsNone(standalone.source_profile)
        self.assertFalse(standalone.requires_recompute_confirmation)
        text = raw.decode('utf-8')
        for forbidden in ['ast.', 'UnitRegistry', 'Quantity(', 'session_token', 'C:\\', '/home/', '__dict__']:
            self.assertNotIn(forbidden, text)
        for n in report.nodes:
            self.assertEqual(float(n.quantity.roundtrip), n.quantity.value)

    def test_profile_drift_requires_confirmation_and_snapshot_is_untrusted(self):
        from unit_trace.serialization import parse_bundle, serialize_bundle
        p = self.base()
        bundle = load_json(serialize_bundle(p, evaluate_project(p)))
        for key, replacement in [('pintVersion', '0.0.1'), ('pythonVersion', '3.12.0'),
                                 ('unitWhitelistVersion', 2), ('dependencies', {'Pint':'0.0.1'}),
                                 ('definitionHashes', {'pint/default_en.txt':'a' * 64})]:
            with self.subTest(key=key):
                changed = copy.deepcopy(bundle)
                changed['report']['profile'][key] = replacement
                loaded = parse_bundle(changed)
                self.assertTrue(loaded.requires_recompute_confirmation)
                self.assertEqual(nodes(evaluate_project(loaded.project))['area'].quantity.value, .0004)
        bundle['report']['nodes'][0]['quantity']['value'] = 12345
        bundle['report']['projectHash'] = 'wrong'
        bundle['report']['rootErrors'] = [{'code': 'fake'}]
        loaded = parse_bundle(bundle)
        self.assertEqual(loaded.project, p)
        self.assertEqual(nodes(evaluate_project(loaded.project))['area'].quantity.value, .0004)
        for source in [copy.deepcopy(bundle), p.to_json()]:
            source['schemaVersion'] = 2
            with self.assertRaises(ProjectValidationError):
                parse_bundle(source)
        invalid = p.to_json()
        invalid['profile'] = 'unknown'
        with self.assertRaises(ProjectValidationError):
            parse_bundle(invalid)
        bundle['report']['profile']['id'] = 'unknown'
        with self.assertRaises(ProjectValidationError):
            parse_bundle(bundle)

    def test_bundle_and_project_have_distinct_size_limits(self):
        from unit_trace.serialization import parse_bundle, serialize_bundle
        p = self.base()
        bundle = load_json(serialize_bundle(p, evaluate_project(p)))
        bundle['report']['snapshotNote'] = 'a' * 140000
        raw = json.dumps(bundle).encode()
        self.assertGreater(len(raw), 131072)
        self.assertEqual(parse_bundle(load_json(raw)).project, p)
        bundle['project']['title'] = 'a' * 131073
        with self.assertRaises(ProjectValidationError) as caught:
            parse_bundle(bundle)
        self.assertEqual(caught.exception.issues[0].code, 'limit_exceeded')
        with self.assertRaises(ProjectValidationError):
            load_json(b' ' * 8388609)
        with self.assertRaises(ProjectValidationError):
            parse_bundle({'schemaVersion':1, 'project':p.to_json(),
                          'report':{'profile':get_profile().to_json(), 'note':'a' * 8388609}})

    def test_hash_is_fixed_utf8_sorted_json_and_stale_report_is_rejected(self):
        from unit_trace.serialization import canonical_project_bytes, project_hash, serialize_bundle
        p = project([], [])
        canonical = b'{"formulas":[],"profile":"unit-trace-scalar-v1","schemaVersion":1,"title":"Synthetic experiment","variables":[]}'
        self.assertEqual(canonical_project_bytes(p), canonical)
        self.assertEqual(project_hash(p), hashlib.sha256(canonical).hexdigest())
        self.assertNotEqual(project_hash(self.base()), project_hash(project([('x','2','cm')], [('area','x**2','m**2')])))
        with self.assertRaises(ProjectValidationError):
            serialize_bundle(p, evaluate_project(self.base()))
        with self.assertRaises(ProjectValidationError):
            serialize_bundle(p, replace(evaluate_project(p), profile=replace(get_profile(), pint_version='0.0.1')))

    def test_profile_schema_and_bundle_envelope_are_strict(self):
        from unit_trace.serialization import parse_bundle, serialize_bundle
        p = self.base()
        original = load_json(serialize_bundle(p, evaluate_project(p)))
        for key, bad in [('schemaVersion', True), ('unitWhitelistVersion', True),
                         ('pintVersion', None), ('definitionHashes', {'pint/default_en.txt':'invalid'}),
                         ('dependencies', {'Pint': 2})]:
            with self.subTest(key=key):
                data = copy.deepcopy(original)
                data['report']['profile'][key] = bad
                with self.assertRaises(ProjectValidationError):
                    parse_bundle(data)
        data = copy.deepcopy(original)
        data['extra'] = 'unexpected'
        with self.assertRaises(ProjectValidationError):
            parse_bundle(data)
        data = copy.deepcopy(original)
        data['report']['profile']['extra'] = 'unexpected'
        with self.assertRaises(ProjectValidationError):
            parse_bundle(data)

    def test_export_has_exact_public_fields_and_enforces_eight_mib(self):
        from unit_trace.serialization import serialize_bundle
        p = self.base()
        report = evaluate_project(p)
        payload = load_json(serialize_bundle(p, report))
        self.assertEqual(set(payload), {'schemaVersion', 'project', 'report'})
        self.assertEqual(set(payload['report']), {'schemaVersion','profile','projectHash','topologicalOrder',
                          'edges','nodes','rootErrors','firstError','changedIds','affectedIds','removedIds'})
        self.assertEqual(set(payload['report']['nodes'][0]), {'id','kind','status','symbolic','substitution',
                          'quantity','traces','conversions','warnings','error','rootErrorIds'})
        self.assertEqual(set(payload['report']['nodes'][0]['quantity']), {'value','roundtrip','unit','dimensionality'})
        huge_node = replace(report.nodes[0], substitution='a' * 8388609)
        huge = replace(report, nodes=(huge_node, *report.nodes[1:]))
        with self.assertRaises(ProjectValidationError) as caught:
            serialize_bundle(p, huge)
        self.assertEqual(caught.exception.issues[0].code, 'limit_exceeded')
