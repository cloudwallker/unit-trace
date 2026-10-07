"""Run the installed entry module outside the repository; preserve input bytes."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_engine import project


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='unit-trace-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'input.json'

    def run_cli(self, *args):
        environment = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
        # Source tests can run without an editable installation; the separate wheel
        # acceptance uses an installed entry point with this variable absent.
        environment['PYTHONPATH'] = str(Path(__file__).parents[1] / 'src')
        return subprocess.run([sys.executable, '-m', 'unit_trace', *map(str, args)],
                              cwd=self.root, env=environment, capture_output=True, timeout=20)

    def write_project(self, data):
        self.source.write_text(json.dumps(data), encoding='utf-8')

    def test_version_and_all_demo_variants(self):
        version = self.run_cli('--version')
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn(b'0.1.0', version.stdout)
        for variant, code in (('normal', 0), ('dimension', 1), ('scale', 0)):
            out = self.root / f'{variant}.json'
            demo = self.run_cli('demo', 'flow', '--variant', variant, '--json', out)
            self.assertEqual(demo.returncode, 0, demo.stderr)
            self.assertEqual(self.run_cli('evaluate', out).returncode, code)

    def test_evaluate_exit_priority_and_three_artifacts(self):
        data = project([('x', '2', 'm'), ('time', '1', 's')], [('double', 'x*2', 'm')]).to_json()
        self.write_project(data)
        outputs = [self.root / f'report.{ext}' for ext in ('json', 'svg', 'html')]
        result = self.run_cli('evaluate', self.source, '--json', outputs[0], '--svg', outputs[1], '--html', outputs[2])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(outputs[0].read_bytes())['report']['nodes'][-1]['quantity']['value'], 4)
        self.assertTrue(all(p.stat().st_size > 100 for p in outputs))
        data['variables'][0]['expected'] = {'min': '3', 'max': '4', 'unit': 'm'}
        self.write_project(data)
        self.assertEqual(self.run_cli('evaluate', self.source).returncode, 2)
        data['formulas'][0]['expression'] = 'x + time'
        self.write_project(data)
        self.assertEqual(self.run_cli('evaluate', self.source).returncode, 1)
        self.assertEqual(self.run_cli('evaluate', self.source, '--json', outputs[0]).returncode, 3)
        data['formulas'][0]['expression'] = 'missing'
        self.write_project(data)
        self.assertEqual(self.run_cli('evaluate', self.source).returncode, 3)

    def test_existing_output_requires_opt_in(self):
        self.write_project(project([('x', '2', 'm')], []).to_json())
        out = self.root / 'result.json'
        out.write_bytes(b'keep this output')
        result = self.run_cli('evaluate', self.source, '--json', out)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(out.read_bytes(), b'keep this output')
        self.assertEqual(self.run_cli('evaluate', self.source, '--json', out, '--overwrite').returncode, 0)
        self.assertIn('report', json.loads(out.read_bytes()))

    def test_overwrite_never_changes_input_or_its_file_aliases(self):
        self.write_project(project([('x', '2', 'm')], []).to_json())
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        aliases = [self.source, self.root / '.' / 'input.json']
        hard = self.root / 'hard.json'
        os.link(self.source, hard)
        aliases.append(hard)
        symbolic = self.root / 'symbolic.json'
        try:
            symbolic.symlink_to(self.source)
        except OSError:
            # Windows symlink privileges are not assumed; clean acceptance records
            # whether the real symlink case was available on its host.
            pass
        else:
            aliases.append(symbolic)
        for alias in aliases:
            with self.subTest(alias=alias.name):
                result = self.run_cli('evaluate', self.source, '--json', alias, '--overwrite')
                self.assertEqual(result.returncode, 3)
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_invalid_io_and_oversize_input_have_safe_errors(self):
        missing = self.root / 'private-name-do-not-print.json'
        result = self.run_cli('evaluate', missing)
        self.assertEqual(result.returncode, 3)
        self.assertNotIn(str(self.root).encode(), result.stderr + result.stdout)
        self.assertNotIn(b'Traceback', result.stderr)
        self.source.write_bytes(b' ' * (8388608 + 1))
        self.assertEqual(self.run_cli('evaluate', self.source).returncode, 3)

    def test_bundle_mismatch_requires_explicit_current_engine_choice(self):
        from unit_trace.engine import evaluate_project
        from unit_trace.serialization import serialize_bundle
        p = project([('x', '2', 'm')], [])
        data = json.loads(serialize_bundle(p, evaluate_project(p)))
        data['report']['profile']['pythonVersion'] = '3.12.synthetic'
        self.write_project(data)
        result = self.run_cli('evaluate', self.source)
        self.assertEqual(result.returncode, 3)
        self.assertIn(b'engine_mismatch', result.stderr)
        output = self.root / 'recomputed.json'
        result = self.run_cli('evaluate', self.source, '--recompute', '--json', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(output.read_bytes())
        self.assertNotEqual(actual['report']['profile']['pythonVersion'], '3.12.synthetic')
        self.assertEqual(actual['report']['nodes'][0]['quantity']['value'], 2)
        data['project']['schemaVersion'] = 2
        self.write_project(data)
        self.assertEqual(self.run_cli('evaluate', self.source, '--recompute').returncode, 3)

    def test_output_aliases_do_not_overwrite_each_other(self):
        self.write_project(project([], []).to_json())
        output = self.root / 'shared.txt'
        result = self.run_cli('evaluate', self.source, '--json', output, '--html', output, '--overwrite')
        self.assertEqual(result.returncode, 3)
        self.assertFalse(output.exists())
