import unittest
from ai_eda.agent.subagents.common import report_feedback


class CompilerFeedbackTests(unittest.TestCase):
    def test_error_before_many_warnings_is_preserved(self):
        error = "design.sv:99: error: Variable 'bus' cannot have multiple drivers."
        report = {"passed": False, "stage": "compile", "checks": [],
                  "stderr": error + "\n" + ("design.sv:100: sorry: warning only\n" * 400)}
        feedback = report_feedback(report)
        self.assertIn(error, feedback)
        self.assertIn("Compiler errors", feedback)

    def test_patch_syntax_feedback_keeps_errors_before_warning_flood(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_eda.agent.subagents.modifier import _syntax_error
        with tempfile.TemporaryDirectory() as tmp:
            teacher=Path(tmp)/'teacher.sv';teacher.write_text('module teacher; endmodule')
            fatal="design.sv:9: error: Unable to bind wire `response' before declaration."
            result=SimpleNamespace(returncode=1,stdout='',stderr=fatal+'\n'+('sorry: warning only\n'*400))
            with patch('ai_eda.agent.subagents.modifier.subprocess.run',return_value=result):
                feedback=_syntax_error({'rtl/core.sv':'module core; endmodule'},
                    {'testbench_path':teacher,'testbench_top':'teacher'})
            self.assertIn(fatal,feedback)
            self.assertNotIn('warning only',feedback)
