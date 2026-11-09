"""Regression for concise, evidence-qualified RV32I repair feedback."""
import copy
import unittest

from ai_eda.agent.subagents.common import report_feedback


class RepairFeedbackTests(unittest.TestCase):
    def test_repeated_retire_failures_do_not_hide_other_testcases(self):
        mismatch = "retire PC/instruction does not match the loaded program"
        checks = ([{"name": "t01_reset", "detail": mismatch}] * 500
                  + [{"name": "t01_reset", "detail": "等待 halted 超时（200 周期）"}]
                  + [{"name": "t02_alu_r", "detail": mismatch}] * 400
                  + [{"name": "t02_alu_r", "detail": "等待 halted 超时（400 周期）"}]
                  + [{"name": "cache_instruction_reuse", "detail": "instruction loop did not reuse cached instruction lines"}])
        report = {"passed": False, "stage": "simulation", "checks": checks}
        original = copy.deepcopy(report)
        text = report_feedback(report)
        self.assertEqual(report, original)
        self.assertEqual(text.count(mismatch), 2)
        self.assertIn("×500", text)
        self.assertIn("×400", text)
        self.assertIn("cache_instruction_reuse", text)
        self.assertIn("等待 halted 超时", text)
        self.assertIn("FETCH/RETIRE", text)
        self.assertEqual(text.count("HALT-TIMEOUT"), 1)
        self.assertIn("待验证的假设", text)
        self.assertLess(len(text), 2500)

    def test_compile_errors_not_reclassified_as_fetch_or_halt(self):
        report = {"passed": False, "stage": "compile", "checks": [],
                  "stderr": "design.sv:1: error: Unknown module type: alu"}
        text = report_feedback(report)
        self.assertIn("Unknown module type: alu", text)
        self.assertNotIn("FETCH/RETIRE", text)
        self.assertNotIn("HALT-TIMEOUT", text)


if __name__ == "__main__":
    unittest.main()
