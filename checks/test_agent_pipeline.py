"""Offline regression tests. Run: .venv/bin/python -m unittest discover -s checks -v"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent import orchestrator
from ai_eda.agent.subagents.common import report_feedback, trace_mismatches, validate_plan
from ai_eda.agent.subagents.modifier import ModifierAgent
from ai_eda.agent.skills.rv32i5_contract import planner_context, coder_context
from ai_eda.agent.subagents.modifier import _repair_trace


def plan(interfaces="output logic [31:0] value"):
    return {"top_module": "demo", "modules": [{"name": "demo", "file": "rtl/nested/demo.sv", "description": "demo", "interfaces": interfaces}]}


class RepairTraceTests(unittest.TestCase):
    def test_timeout_preserves_observed_test_trace(self):
        trace = [{'test': 't01_reset', 'event': 'mem_read'}, {'test': 't05_forward', 'event': 'test_start'}]
        self.assertEqual(_repair_trace({'timed_out': True, 'trace': trace}, {'simulation_timeout'}), trace)
        self.assertEqual(_repair_trace({'trace': trace}, {'t05_forward'}), trace[1:])


def failure():
    return {"passed": False, "stage": "simulation", "return_code": 1,
            "checks": [{"name": "t05_forward", "detail": "x4 expected 2 got 0"}],
            "trace": [{"test": "t05_forward", "cycle": 5, "expected_x4": 2, "x4": 0}],
            "test_suites": [{"name": "base", "passed": False, "skipped": False}]}


class FeedbackTests(unittest.TestCase):
    def test_reference_trace_is_not_a_failed_assertion(self):
        report = failure()
        report["trace"].insert(0, {"test": "t13_dft", "cycle": 1, "mag": -999, "expected_mag": 0})
        messages = trace_mismatches(report)
        self.assertEqual(len(messages), 1)
        self.assertIn("x4=0", messages[0])
        self.assertNotIn("mag=", report_feedback(report))

    def test_unlabelled_actual_fields_and_zero_values(self):
        report = failure()
        report["trace"] = [{"actual_x": 0, "expected_x": 1}, {"mag": -1, "expected_mag": 0}]
        self.assertEqual(len(trace_mismatches(report)), 1)
        self.assertIn("x=0", trace_mismatches(report)[0])

    def test_halt_hint_requires_majority_and_does_not_invent_pc_motion(self):
        report = failure()
        timeouts = [{"name": str(i), "detail": "等待 halted 超时"} for i in range(2)]
        report["checks"] = timeouts + [{"name": "forward", "detail": "wrong value"}]
        feedback = report_feedback(report)
        self.assertEqual(feedback.count("HALT-TIMEOUT"), 1)
        self.assertNotIn("imem_addr 仍在变化", feedback)
        report["checks"] += [{"name": "mem", "detail": "wrong value"}]
        self.assertNotIn("HALT-TIMEOUT", report_feedback(report))

    def test_full_interface_contract_survives(self):
        interfaces = "input logic [31:0] port; " * 100
        self.assertEqual(validate_plan(plan(interfaces))["modules"][0]["interfaces"], interfaces)

    def test_tier_context_is_project_specific(self):
        self.assertEqual(planner_context("stream_filter"), "")
        for project, level in [("rv32i5_cache", 1), ("rv32i5_predict", 2), ("rv32i5_ooo", 3)]:
            self.assertIn(f"Target: L{level}", planner_context(project))
            self.assertIn(f"Target: L{level}", coder_context(project))


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, project):
        calls = []
        repair_count = 0
        def stream(_client, messages):
            nonlocal repair_count
            calls.append(json.loads(json.dumps(messages)))
            system = messages[0]["content"]
            if "Spec Parser" in system:
                answer = {"sufficient": True, "missing": [], "questions": [], "spec_addendum": ""}
            elif "RTL Planner" in system:
                answer = plan(' '.join(f'output logic [31:0] value_{i};' for i in range(100)))
            elif "RTL Modifier" in system:
                repair_count += 1
                answer = {"files": [{"path": "rtl/nested/demo.sv", "content": f"module demo; // repair {repair_count}\nendmodule"}], "notes": "repair"}
            else:
                yield {"type": "done", "answer": "module demo; endmodule", "usage": {}, "finish_reason": "stop"}
                return
            yield {"type": "done", "answer": json.dumps(answer), "usage": {}, "finish_reason": "stop"}

        class Client:
            def stream_chat_detail(self, messages):
                return stream(self, messages)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(orchestrator, "AGENT_RUNS_ROOT", Path(tmp)), \
                 patch("ai_eda.agent.subagents.base.RunContext.make_client", return_value=Client()), \
                 patch("ai_eda.agent.subagents.tester.test_rtl", side_effect=[failure(), failure(), {"passed": True, "stage": "simulation", "return_code": 0}]):
                result = orchestrator.run_agent(project_id=project, max_repair_attempts=2)
            run_dir = next(Path(tmp).iterdir())
            payload = json.loads((run_dir / "result.json").read_text())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["tester_attempts"], 3)
            coder_event = next(e for e in result["events"] if e["node_id"] == "coder")
            self.assertEqual(coder_event["module"], "demo")
            self.assertEqual(coder_event["file"], "rtl/nested/demo.sv")
            self.assertEqual((run_dir / "project/rtl/nested/demo.sv").read_text(), "module demo; // repair 2\nendmodule")
            initial = json.loads((run_dir / "artifacts/rtl_manifest.json").read_text())["files"][0]
            repaired = json.loads((run_dir / "artifacts/rtl_manifest_attempt2.json").read_text())["files"][0]
            self.assertEqual(repaired["implementation"], "model_repair")
            self.assertEqual(repaired["original_implementation"], "model")
            self.assertEqual((run_dir / initial["artifact"]).read_text(), "module demo; endmodule\n")
            for h in (run_dir / "handoffs").glob("*.json"):
                record = json.loads(h.read_text())
                self.assertEqual(record["schema_version"], 1)
            prompts = [m for m in calls if "RTL Modifier" in m[0]["content"]]
            self.assertEqual(len(prompts), 2)
            if project.startswith("rv32i5"):
                self.assertIn("本轮失败指纹与上一轮相同", prompts[-1][-1]["content"])
                self.assertIn("连续失败的测试", prompts[-1][-1]["content"])
                self.assertIn("t05_forward", prompts[-1][-1]["content"])
                self.assertTrue((run_dir / "artifacts/repair_packet_attempt2.json").is_file())
            else:
                self.assertNotIn("RV32I", prompts[0][0]["content"])
                self.assertFalse(list((run_dir / "artifacts").glob("repair_packet*")))
            if project == "rv32i5_predict":
                for name in ("RTL Planner", "digital IC engineer", "RTL Modifier"):
                    model_messages = next(m for m in calls if name in m[0]["content"])
                    self.assertIn("Target: L2", "\n".join(m["content"] for m in model_messages))
            # Resume loads nested RTL and uses machine identity even if the title changes.
            event_path = run_dir / "events.json"
            event_data = json.loads(event_path.read_text())
            event_data["status"] = "running"
            event_data["events"] = [{"node_id": "coder", "module": "demo", "title": "new title", "status": "running"}]
            event_path.write_text(json.dumps(event_data))
            with patch.object(orchestrator, "AGENT_RUNS_ROOT", Path(tmp)):
                resumed = orchestrator._load_resume_source(run_dir.name)
            self.assertEqual(resumed["module"], "demo")
            self.assertIn("rtl/nested/demo.sv", resumed["project_files"])
            event_data["events"] = [{"node_id": "coder", "title": "03 · Coder · demo", "status": "failed"}]
            event_path.write_text(json.dumps(event_data))
            with patch.object(orchestrator, "AGENT_RUNS_ROOT", Path(tmp)):
                self.assertEqual(orchestrator._load_resume_source(run_dir.name)["module"], "demo")
            event_data["events"] = [{"node_id": "parser", "status": "waiting_input"}]
            event_path.write_text(json.dumps(event_data))
            with patch.object(orchestrator, "AGENT_RUNS_ROOT", Path(tmp)):
                self.assertEqual(orchestrator._load_resume_source(run_dir.name)["stage"], "parser")

    def test_rv32i_repair_loop_and_resume(self):
        self.run_pipeline("rv32i5")

    def test_advanced_tier_reaches_all_model_roles(self):
        self.run_pipeline("rv32i5_predict")

    def test_fifo_repair_loop(self):
        self.run_pipeline("stream_filter")

    def test_full_spec_tail_is_visible_to_modifier(self):
        agent = object.__new__(ModifierAgent)
        spec = "x" * 46000 + "TAIL_ACCEPTANCE_REQUIREMENT"
        message = agent._initial_message(spec, plan(), {}, failure(), 1)
        self.assertIn("TAIL_ACCEPTANCE_REQUIREMENT", message)


if __name__ == "__main__":
    unittest.main()
