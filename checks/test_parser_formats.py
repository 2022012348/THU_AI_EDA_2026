import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.parser import ParserAgent


class ParserFormatTests(unittest.TestCase):
    def run_parser(self, answer):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runtime = RunContext(
            run_dir=Path(tmp.name), options={},
            begin_event=lambda *args: {"step": 1},
            finish_event=lambda *args, **kwargs: None,
            persist=lambda *args: None, emit=lambda *args: None,
            check_cancel=lambda: None, request_input=None,
        )
        spec = runtime.write_text_artifact("spec.md", "Original spec")
        handoff = runtime.write_handoff("input", "parser", {"artifacts": {"spec": spec}})
        with patch.object(runtime, "call_model", return_value={"answer": json.dumps(answer)}):
            out = ParserAgent(runtime).run(handoff)
        ref = runtime.read_handoff(out)["payload"]["artifacts"]["spec"]
        return runtime.read_text_artifact(ref)

    def test_alternative_verdict_preserves_list_addendum(self):
        result = self.run_parser({"verdict": "sufficient_after_addendum", "blocking_questions": [],
                                  "spec_addendum": ["assumption one", "assumption two"]})
        self.assertIn("Original spec", result)
        self.assertIn("- assumption one", result)
        self.assertIn("- assumption two", result)

    def test_blocking_question_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "reset polarity"):
            self.run_parser({"verdict": "sufficient", "blocking_questions": ["reset polarity"]})
