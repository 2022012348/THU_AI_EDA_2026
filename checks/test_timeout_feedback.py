import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.rtl.runner import test_rtl, parse_partial_testbench_output
from ai_eda.agent.subagents.common import report_feedback


class TimeoutFeedbackTests(unittest.TestCase):
    def test_complete_large_output_keeps_raw_log_and_suite_verdict_outside_excerpt(self):
        line = 'AI_EDA_TRACE|cycle=4|test=loop|event=retire|detail=observed\n'
        raw = line * 1000 + 'AI_EDA_SUITE|name=base|passed=0|skipped=0\n' + line * 1000
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tb, rtl = root / 'tb.sv', root / 'rtl.sv'
            tb.write_text('module tb; endmodule')
            rtl.write_text('module core; endmodule')
            results = [subprocess.CompletedProcess(['iverilog'], 0, '', ''),
                       subprocess.CompletedProcess(['vvp'], 0, raw, '')]
            with patch('ai_eda.rtl.runner.subprocess.run', side_effect=results), \
                 patch('ai_eda.rtl.runner.synthesize_metrics', return_value={}):
                report = test_rtl(task_name='test', testbench_path=tb, testbench_top='tb', rtl_path=rtl, run_dir=root/'out')
            self.assertFalse(report['passed'])
            self.assertFalse(report['test_suites'][0]['passed'])
            self.assertNotIn('AI_EDA_SUITE', report['stdout'])
            self.assertLess(len(report['stdout']), 21000)
            self.assertEqual(Path(report['stdout_log']).read_text(), raw)
            self.assertEqual(report['diagnostic_counts']['trace_events_observed'], 2000)

    def test_repeated_failures_are_bounded_with_counts_and_final_progress(self):
        text = ''.join(f'AI_EDA_TRACE|cycle={i}|test=loop|event=retire\nCHECK: loop — wrong retirement\n'
                       for i in range(5000))
        trace, checks, counts = parse_partial_testbench_output(text)
        self.assertLess(len(trace), 100)
        self.assertEqual(trace[0]['cycle'], 0)
        self.assertEqual(trace[-1]['cycle'], 4999)
        self.assertEqual(checks, [{'name': 'loop', 'detail': 'wrong retirement', 'count': 5000}])
        self.assertEqual(counts['trace_events_observed'], 5000)
        feedback = report_feedback({'passed': False, 'stage': 'simulation', 'checks': checks})
        self.assertIn('×5000', feedback)

    def test_partial_teacher_failures_and_trace_survive_wall_clock_timeout(self):
        text = ('AI_EDA_TRACE|cycle=31|test=forward|event=check_reg|detail=x4=0\n'
                'CHECK: forward — x4 expected 2 got 0\nPASS: earlier_suite\n')
        for output in (text, text.encode('utf-8')):
            with self.subTest(bytes=isinstance(output, bytes)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tb, rtl = root / 'tb.sv', root / 'rtl.sv'
                tb.write_text('module tb; endmodule')
                rtl.write_text('module core; endmodule')
                compile_ok = subprocess.CompletedProcess(['iverilog'], 0, '', '')
                timeout = subprocess.TimeoutExpired(['vvp'], 20, output=output, stderr=b'')
                with patch('ai_eda.rtl.runner.subprocess.run', side_effect=[compile_ok, timeout]):
                    report = test_rtl(task_name='test', testbench_path=tb, testbench_top='tb', rtl_path=rtl)
                self.assertFalse(report['passed'])
                self.assertTrue(report['partial_output'])
                self.assertTrue(report['timed_out'])
                self.assertEqual(report['trace'][0]['cycle'], 31)
                self.assertEqual([c['name'] for c in report['checks']], ['forward', 'simulation_timeout'])
                self.assertIn('x4 expected 2 got 0', report_feedback(report))
