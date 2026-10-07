"""Offline artifacts must preserve real results and treat labels only as text."""

from html.parser import HTMLParser
import json
import unittest
import xml.etree.ElementTree as ET

from unit_trace.engine import evaluate_project
from unit_trace.serialization import parse_bundle, serialize_bundle
from unit_trace.validation import parse_project
from tests.test_engine import project


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    def handle_data(self, data):
        self.text.append(data)


class ExportTests(unittest.TestCase):
    def fixture(self):
        data = project([('length', '2', 'cm'), ('time', '0', 's')],
                       [('bad', 'length + time', None), ('blocked', 'bad * 2', None),
                        ('zero', 'time * 1', 'ms')]).to_json()
        data['title'] = '</script><img src=x onerror=alert(1)>\u2028\u2029'
        data['variables'][0]['label'] = '<svg onload=alert(1)>&"'
        data['variables'][0]['expected'] = {'min': '3', 'max': '4', 'unit': 'cm'}
        p = parse_project(data)
        return p, evaluate_project(p)

    def test_svg_is_parseable_text_only_with_all_statuses(self):
        from unit_trace.exports import render_svg
        p, report = self.fixture()
        svg = render_svg(p, report)
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
        text = ''.join(root.itertext())
        self.assertIn(p.variables[0].label, text)
        for status in ('ok', 'warning', 'error', 'blocked'):
            self.assertIn(status, text)
        for element in root.iter():
            self.assertNotIn(element.tag.split('}')[-1], ('script', 'foreignObject', 'image', 'use'))
            self.assertFalse(any(k.lower().startswith('on') or k.endswith('href') for k in element.attrib))

    def test_html_is_offline_snapshot_with_complete_explanations(self):
        from unit_trace.exports import render_html
        p, report = self.fixture()
        html = render_html(p, report)
        parsed = Elements()
        parsed.feed(html)
        self.assertNotIn('script', parsed.tags)
        self.assertNotIn('img', parsed.tags)
        self.assertFalse(any(k in ('src', 'href', 'srcdoc') or k.startswith('on') for k, _ in parsed.attrs))
        text = ''.join(parsed.text)
        self.assertIn('snapshot', text.lower())
        self.assertIn(p.title, text)
        for expected in ('dimension_mismatch', 'range_outside', 'blocked', '1000', 'length + time'):
            self.assertIn(expected, text)
        for n in report.nodes:
            self.assertIn(n.id, text)
        self.assertIn(report.project_hash, text)

    def test_bundle_recomputes_instead_of_trusting_snapshot(self):
        p, report = self.fixture()
        data = json.loads(serialize_bundle(p, report))
        data['report']['nodes'] = [{'id': 'fabricated', 'quantity': 999}]
        loaded = parse_bundle(data)
        actual = evaluate_project(loaded.project)
        self.assertEqual(actual.project_hash, report.project_hash)
        self.assertEqual([n.status for n in actual.nodes], ['warning', 'ok', 'error', 'blocked', 'ok'])

    def test_exports_reject_a_stale_report(self):
        from unit_trace.exports import render_html, render_svg
        p, report = self.fixture()
        other = project([('different', '1', 'm')], [])
        from unit_trace.models import ProjectValidationError
        for renderer in (render_html, render_svg):
            with self.subTest(renderer=renderer.__name__), self.assertRaises(ProjectValidationError):
                renderer(other, report)

    def test_all_eight_templates_keep_each_node_explanation(self):
        from pathlib import Path
        from unit_trace.exports import render_html
        from unit_trace.validation import load_json
        root = Path(__file__).parents[1] / 'src/unit_trace/templates'
        for identifier in ('flow', 'density', 'spring', 'electric', 'energy',
                           'diffusion', 'concentration', 'pendulum'):
            with self.subTest(template=identifier):
                p = parse_project(load_json((root / identifier / 'normal.json').read_bytes()))
                report = evaluate_project(p)
                parsed = Elements()
                parsed.feed(render_html(p, report))
                text = ''.join(parsed.text)
                for n in report.nodes:
                    self.assertIn(n.symbolic, text)
                    self.assertIn(n.quantity.roundtrip, text)
                    self.assertIn(n.quantity.dimensionality, text)
                self.assertEqual(parsed.tags.count('summary'), len(report.nodes))
