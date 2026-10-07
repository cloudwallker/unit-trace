import unittest

from unit_trace.models import ProjectValidationError
from unit_trace.validation import parse_project
from unit_trace.graph import build_graph


def data(variables=(), formulas=()):
    return {'schemaVersion': 1, 'profile': 'unit-trace-scalar-v1', 'title': '',
            'variables': [{'id': v, 'label': '', 'value': '1', 'unit': '1'} for v in variables],
            'formulas': [{'id': name, 'label': '', 'expression': text} for name, text in formulas]}


class GraphTests(unittest.TestCase):
    def test_forward_refs_and_stable_topology(self):
        graph = build_graph(parse_project(data(['x','y'], [('a','b+x'), ('b','y'), ('c','x')])))
        self.assertEqual(graph.order, ('x', 'y', 'b', 'a', 'c'))
        self.assertEqual(graph.edges, (('b','a'), ('x','a'), ('y','b'), ('x','c')))
        self.assertEqual(graph.dependants['x'], ('a', 'c'))
        self.assertEqual(graph.dependants['c'], ())

    def test_duplicate_ids_across_namespace(self):
        with self.assertRaises(ProjectValidationError) as caught:
            build_graph(parse_project(data(['a'], [('a','1')])))
        issue = caught.exception.issues[0]
        self.assertEqual(issue.code, 'duplicate_id')
        self.assertEqual(issue.related_ids, ('a',))

    def test_missing_refs_are_all_reported_and_located(self):
        with self.assertRaises(ProjectValidationError) as caught:
            build_graph(parse_project(data([], [('a','x+y'), ('b','z')])))
        self.assertEqual([i.related_ids for i in caught.exception.issues], [('x',), ('y',), ('z',)])
        self.assertEqual(caught.exception.issues[0].field, 'formulas[0].expression')
        self.assertEqual(caught.exception.issues[0].span.to_json(), {'start': 0, 'end': 1})

    def test_closed_cycle_and_self_reference(self):
        for formulas, cycle in [([('a','b'),('b','a')], ('a','b','a')), ([('a','a')], ('a','a'))]:
            with self.assertRaises(ProjectValidationError) as caught:
                build_graph(parse_project(data([], formulas)))
            self.assertEqual(caught.exception.issues[0].code, 'cycle')
            self.assertEqual(caught.exception.issues[0].related_ids, cycle)

    def test_two_branches_and_empty(self):
        graph = build_graph(parse_project(data(['x','y'], [('a','x'),('b','y'),('c','a'),('d','b')])))
        self.assertEqual(graph.order, ('x','y','a','b','c','d'))
        self.assertEqual(build_graph(parse_project(data())).order, ())
