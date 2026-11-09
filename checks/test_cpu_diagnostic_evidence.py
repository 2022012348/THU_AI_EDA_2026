import unittest
from ai_eda.agent.skills.cpu_diagnostics import summarize_cpu_report


class FailureTraceTests(unittest.TestCase):
    def test_samples_failed_test_even_when_not_in_global_windows(self):
        r = {"passed": False, "stage": "simulation",
             "checks": [{"name": "reset", "detail": "x1 wrong"}],
             "trace": [{"test": "other", "event": "start"},
                       {"test": "reset", "event": "check_reg", "detail": "x1 got=0 FAIL"},
                       {"test": "other", "event": "end"}]}
        packet = summarize_cpu_report(r, first_trace_events=1, last_trace_events=1)
        self.assertEqual(packet["failure_trace_samples"][0]["testcase"], "reset")
        self.assertEqual(packet["failure_trace_samples"][0]["events"][0]["detail"], "x1 got=0 FAIL")
