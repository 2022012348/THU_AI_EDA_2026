"""Black-box L1 final-word redirect verification and report integration."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent import runs as agent_runs
from ai_eda.agent.reporting import report_summary
from ai_eda.agent.skills.l1_icache_probe import add_l1_icache_probe_to_report, run_l1_icache_flush_probe
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.tester import TesterAgent
from ai_eda.agent.subagents.common import report_feedback

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'content/agent/skills/rv32i5_l1_reference/icache.sv'
PLAN = {'top_module': 'icache', 'modules': [{'name': 'icache', 'file': 'rtl/icache.sv'}]}


def buggy_source():
    # Reproduce the bug narrowly: during last-word flush, compare old epoch
    # without considering the contemporaneous flush signal. Also remove the
    # response's combinational flush gating to expose the stale response.
    text = REFERENCE.read_text()
    text = text.replace('if (discard_refill || flush || flush_epoch != refill_epoch) begin',
                        'if (discard_refill || flush_epoch != refill_epoch) begin')
    text = text.replace('resp_valid_r && !flush && (resp_epoch == flush_epoch)', 'resp_valid_r')
    return text


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog unavailable')
class ProbeTests(unittest.TestCase):
    def test_reference_passes_and_edge_defect_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source, expected in [(REFERENCE.read_text(), 'passed'), (buggy_source(), 'failed')]:
                rtl = root / 'icache.sv'
                rtl.write_text(source)
                result = run_l1_icache_flush_probe(plan=PLAN, files={'rtl/icache.sv': source},
                                                  combined_path=rtl, output_dir=root / expected)
                self.assertEqual(result['status'], expected, result)
                self.assertEqual(result['observations'][0]['name'], 'icache_word_offsets')
                self.assertEqual(result['observations'][0]['status'], 'passed')
                report = {'passed': False, 'stage': 'simulation', 'directed_checks': [result]}
                self.assertIn('sixteen cached-word reads', report_feedback(report))
                self.assertTrue((root / expected / 'simulation.log').is_file())
                if expected == 'failed':
                    self.assertIn('flush', result['check_name'])

    def test_manual_retest_cannot_skip_edge_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / 'old'; old.mkdir()
            ctx = RunContext(run_dir=old, options={}, begin_event=lambda *a: {},
                             finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            ctx.write_json_artifact('plan.json', PLAN)
            ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest({'rtl/icache.sv':buggy_source()}, 'coder'))
            (old / 'events.json').write_text(json.dumps({'project_id':'rv32i5_cache',
                'events':[{'node_id':'tester','status':'passed'}]}))
            with patch.object(agent_runs, 'AGENT_RUNS_ROOT', root), \
                 patch.object(agent_runs, 'test_rtl', return_value={'passed':True,'stage':'simulation','checks':[]}), \
                 patch.object(agent_runs, 'load_agent_run', side_effect=lambda run_id: json.loads((root/run_id/'events.json').read_text())):
                result = agent_runs.retest_agent_run('old')
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['report']['teacher_passed'])
            self.assertEqual(result['report']['directed_checks'][0]['status'], 'failed')

    def test_tester_routes_directed_failure_to_modifier_with_teacher_result_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            def begin(*args):
                event = {'step': 1, 'node_id': 'tester'}
                events.append(event)
                return event
            def finish(event, status, **fields):
                event.update(fields, status=status)
            project = {'id':'rv32i5_cache', 'task_name':'test', 'testbench_path':root/'unused.sv',
                       'testbench_top':'unused', 'power_testbench_path':root/'unused.sv',
                       'power_testbench_top':'unused', 'expected_cpu_level':1}
            ctx = RunContext(run_dir=root, options={'project':project}, begin_event=begin,
                             finish_event=finish, persist=lambda *a: None, emit=lambda *a: None,
                             check_cancel=lambda: None, request_input=None)
            spec = ctx.write_text_artifact('spec.md','spec')
            plan = ctx.write_json_artifact('plan.json',PLAN)
            files = {'rtl/icache.sv': buggy_source()}
            manifest = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest(files, 'coder'))
            handoff = ctx.write_handoff('coder','tester',{'artifacts':{'spec':spec,'plan':plan,'rtl_manifest':manifest}})
            with patch('ai_eda.agent.subagents.tester.test_rtl', return_value={
                'passed':True, 'stage':'simulation', 'checks':[], 'test_suites':[{'name':'base','passed':True,'skipped':False}]}):
                result = TesterAgent(ctx).run(handoff,1)
            payload = ctx.read_handoff(result)['payload']
            report = ctx.read_json_artifact(payload['artifacts']['report'])
            self.assertEqual(result.name,'tester_to_modifier_attempt1.json')
            self.assertTrue(report['teacher_passed'])
            self.assertFalse(report['passed'])
            self.assertEqual(report['directed_checks'][0]['status'], 'failed')
            self.assertIn('additional verification', report_summary(report))
            self.assertIn(report['checks'][0]['name'], report_feedback(report))
            self.assertEqual(events[0]['status'], 'failed')


class UnsupportedTests(unittest.TestCase):
    def test_unrecognized_interface_is_explicit_and_never_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = REFERENCE.read_text().replace('input  logic        halted,', 'input logic mystery_control,')
            rtl = root/'icache.sv'; rtl.write_text(source)
            result = run_l1_icache_flush_probe(plan=PLAN, files={'rtl/icache.sv':source},
                                               combined_path=rtl,output_dir=root/'probe')
            self.assertEqual(result['status'],'unsupported')
            report = {'passed':True,'stage':'simulation','checks':[]}
            add_l1_icache_probe_to_report(report,result)
            self.assertFalse(report['passed'])
            self.assertTrue(report['teacher_passed'])
            self.assertIn('未完成',report['checks'][0]['detail'])


if __name__ == '__main__':
    unittest.main()
