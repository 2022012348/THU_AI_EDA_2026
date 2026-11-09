"""Ensure supported control failures stop the run and other topologies are explicit."""
import unittest
from ai_eda.agent.skills.l1_id_hazard_probe import add_l1_id_hazard_to_report


class IdHazardReportTests(unittest.TestCase):
    def test_failure_stops_overall_pass_without_changing_teacher_result(self):
        report = {'passed': True, 'teacher_passed': True, 'checks': [], 'test_suites': []}
        add_l1_id_hazard_to_report(report, {'status': 'failed', 'passed': False,
            'checks': [{'name': 'l1_load_use_bubble', 'detail': 'bubble missing'}]})
        self.assertFalse(report['passed'])
        self.assertTrue(report['teacher_passed'])
        self.assertEqual(report['checks'][0]['name'], 'l1_load_use_bubble')
        self.assertFalse(report['test_suites'][0]['skipped'])

    def test_different_architecture_is_marked_uncovered_not_passed(self):
        report = {'passed': True, 'teacher_passed': True, 'checks': [], 'test_suites': []}
        add_l1_id_hazard_to_report(report, {'status': 'not_covered', 'passed': None,
                                            'detail': 'unsupported topology'})
        self.assertTrue(report['passed'])
        self.assertIsNone(report['directed_checks'][0]['passed'])
        self.assertTrue(report['test_suites'][0]['skipped'])

    def test_previously_covered_test_cannot_be_evaded_by_interface_change(self):
        report = {'passed': True, 'teacher_passed': True, 'checks': [], 'test_suites': []}
        add_l1_id_hazard_to_report(report, {'status': 'not_covered', 'passed': None, 'detail': 'changed'}, required=True)
        self.assertFalse(report['passed'])
        self.assertEqual(report['directed_checks'][0]['status'], 'error')
        self.assertFalse(report['test_suites'][0]['skipped'])
