import copy
import unittest
from ai_eda.agent.repair_focus import make_repair_ticket,focused_report
from ai_eda.agent.repair_control import evaluate_repair
from ai_eda.agent.subagents.modifier import _validate_ticket

class RepairFocusTests(unittest.TestCase):
    def fixture(self):
        return {'passed':False,'stage':'simulation',
            'checks':[{'name':'later','detail':'wrong'},{'name':'earlier','detail':'wrong'}],
            'teacher_checks':[{'name':'later','detail':'wrong'},{'name':'earlier','detail':'wrong'}],
            'trace':[{'test':'earlier','cycle':1},{'test':'later','cycle':2}],
            'retirement_observation':{'status':'observed','observations':[], 'sequence_observations':[
                {'test':'earlier','previous_pc':'00000004','previous_insn':'00408093','pc':'00000004','expected_pc':'00000008'}]},
            'data_bus_observation':{'status':'observed','tests':[{'test':'earlier'},{'test':'later'}]},
            'directed_checks':[{'name':'cache_probe','detail':'failed'}],
            'structural_diagnostics':{'issues':['unrelated warning']}}

    def test_ai_view_is_single_case_and_original_verdict_is_unchanged(self):
        report=self.fixture(); original=copy.deepcopy(report)
        view=focused_report(report); ticket=view['repair_ticket']
        self.assertEqual(ticket['kind'],'retirement_fallthrough')
        self.assertEqual(ticket['testcase'],'earlier')
        self.assertEqual([c['name'] for c in view['checks']],['earlier'])
        self.assertEqual(view['directed_checks'],[])
        self.assertNotIn('structural_diagnostics',view)
        self.assertEqual(view['data_bus_observation']['tests'],[{'test':'earlier'}])
        self.assertEqual(report,original)
        self.assertEqual(make_repair_ticket(report)['id'],ticket['id'])

    def test_fewer_unrelated_failures_cannot_hide_the_same_retirement_counterexample(self):
        before=self.fixture(); after=self.fixture()
        after['checks']=after['checks'][1:]
        evaluation=evaluate_repair(before,after)
        self.assertFalse(evaluation['accepted'])
        self.assertIn('ticket not resolved',str(evaluation['reasons']))
        after['retirement_observation']['sequence_observations']=[]
        self.assertTrue(evaluate_repair(before,after)['accepted'])

    def test_response_and_observation_must_address_the_current_ticket(self):
        ticket=make_repair_ticket(self.fixture())
        with self.assertRaises(ValueError):_validate_ticket({},ticket,True)
        with self.assertRaises(ValueError):_validate_ticket({'ticket_id':ticket['id'],
            'request_observation':{'testcase':'later'}},ticket,True)
        _validate_ticket({'ticket_id':ticket['id'],
            'request_observation':{'testcase':'earlier'}},ticket,True)
