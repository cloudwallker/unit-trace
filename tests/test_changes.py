import unittest

from unit_trace.validation import parse_project
from tests.test_engine import project


class ChangeTests(unittest.TestCase):
    def base(self):
        return project([('a', '2', 'm'), ('b', '3', 'm')],
                       [('first', 'a * 2', 'm'), ('second', 'first * 3', 'm'), ('other', 'b * 2', 'm')])

    def test_variable_and_evaluation(self):
        from unit_trace.changes import compare_projects
        from unit_trace.engine import evaluate_project
        old = self.base()
        data = old.to_json()
        data['variables'][0]['value'] = '4'
        current = parse_project(data)
        changes = compare_projects(current, old)
        self.assertEqual(changes.changed_ids, ('a',))
        self.assertEqual(changes.affected_ids, ('a', 'first', 'second'))
        self.assertEqual(changes.removed_ids, ())
        report = evaluate_project(current, old)
        self.assertEqual(report.changed_ids, changes.changed_ids)
        self.assertEqual(report.affected_ids, changes.affected_ids)
        self.assertEqual(compare_projects(old, None).affected_ids, ())

    def test_old_and_new_graph_union_and_removed_nodes(self):
        from unit_trace.changes import compare_projects
        old = self.base()
        data = old.to_json()
        data['formulas'][0]['expression'] = 'b * 2'
        data['formulas'][1]['expression'] = 'b * 3'
        data['variables'][0]['value'] = '4'
        current = parse_project(data)
        changes = compare_projects(current, old)
        self.assertEqual(changes.changed_ids, ('a', 'first', 'second'))
        self.assertEqual(changes.affected_ids, ('a', 'first', 'second'))
        data = old.to_json()
        data['variables'].pop(0)
        data['formulas'][0]['expression'] = 'b * 2'
        changes = compare_projects(parse_project(data), old)
        self.assertEqual(changes.removed_ids, ('a',))
        self.assertEqual(changes.changed_ids, ('first', 'a'))
        self.assertEqual(changes.affected_ids, ('first', 'second'))

    def test_metadata_and_equivalent_output_units(self):
        from unit_trace.changes import compare_projects
        old = self.base()
        data = old.to_json()
        data['title'] = 'Edited title'
        data['variables'][0]['label'] = 'Edited label'
        data['formulas'][0]['expected'] = {'min': '0', 'max': '10', 'unit': 'm'}
        self.assertEqual(compare_projects(parse_project(data), old).changed_ids, ())
        data['formulas'][0]['outputUnit'] = 'm * 1'
        changes = compare_projects(parse_project(data), old)
        self.assertEqual(changes.changed_ids, ('first',))
        self.assertEqual(changes.affected_ids, ('first', 'second'))

    def test_added_and_kind_changed_ids(self):
        from unit_trace.changes import compare_projects
        old = project([('a', '2', 'm')], [])
        current = project([('new', '1', 'm')], [('a', 'new * 2', None)])
        changes = compare_projects(current, old)
        self.assertEqual(changes.changed_ids, ('new', 'a'))
        self.assertEqual(changes.affected_ids, ('new', 'a'))
        self.assertEqual(changes.removed_ids, ())
