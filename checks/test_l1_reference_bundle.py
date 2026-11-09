"""Regression coverage of the L1 reference bundle and its effective contract."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent.skills.rv32i5_l1_reference import build_reference_plan, load_reference
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.coder import CoderAgent


class ReferenceBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = []
        def begin(node_id, node_type, title, prompt, attempt=1):
            event = {"step": len(self.events) + 1, "node_id": node_id, "title": title}
            self.events.append(event)
            return event
        def finish(event, status, **fields):
            event.update(status=status, **fields)
        self.runtime = RunContext(
            run_dir=self.root, options={"project": {"id": "rv32i5_cache"}},
            begin_event=begin, finish_event=finish, persist=lambda *a, **k: None,
            emit=lambda *a: None, check_cancel=lambda: None, request_input=None,
        )
        network_guard = patch.object(self.runtime, 'make_client', side_effect=AssertionError('network disabled in reference regression'))
        network_guard.start()
        self.addCleanup(network_guard.stop)
        self.model_plan = {"top_module": "rv32i5", "project_name": "model_plan", "modules": [
            {"name": "rv32i5", "file": "rtl/rv32i5.sv", "description": "top", "interfaces": "input logic wrong"},
            {"name": "extra", "file": "rtl/extra.sv", "description": "extra", "interfaces": "input logic wrong"},
        ]}
        spec = self.runtime.write_text_artifact("spec.md", "l1 spec")
        plan = self.runtime.write_json_artifact("plan.json", self.model_plan)
        self.handoff = self.runtime.write_handoff("planner", "coder", {"artifacts": {"spec": spec, "plan": plan}})

    def test_full_reference_is_closed_and_uses_actual_ports(self):
        with patch.object(self.runtime, "call_model", side_effect=AssertionError("model not expected")):
            out = CoderAgent(self.runtime).run(self.handoff)
        artifacts = self.runtime.read_handoff(out)["payload"]["artifacts"]
        self.assertEqual(artifacts["plan"], "artifacts/plan_reference.json")
        actual_plan = self.runtime.read_json_artifact(artifacts["plan"])
        manifest = self.runtime.read_json_artifact(artifacts["rtl_manifest"])
        self.assertEqual(self.runtime.read_json_artifact("artifacts/plan.json"), self.model_plan)
        files = {entry["path"]: entry for entry in manifest["files"]}
        self.assertIn("rtl/alu.sv", files)
        self.assertNotIn("rtl/extra.sv", files)
        self.assertEqual({m["file"] for m in actual_plan["modules"]}, set(files))
        self.assertTrue(all(entry["implementation"] == "reference" for entry in files.values()))
        self.assertTrue(all(event["implementation"] == "reference" for event in self.events))
        ex = next(m for m in actual_plan["modules"] if m["name"] == "ex_stage")
        self.assertIn("input  logic        mem_stall", ex["interfaces"])
        self.assertEqual(actual_plan["implementation_source"], "reference")
        # Immutable snapshot remains unchanged if the mutable work file changes.
        snapshot = files["rtl/alu.sv"]["artifact"]
        source = self.runtime.read_text_artifact(snapshot)
        (self.root / "project/rtl/alu.sv").write_text("modified")
        self.assertEqual(self.runtime.read_text_artifact(snapshot), source)

    def test_reference_bundle_missing_dependency_fails_closed(self):
        reference = load_reference("rv32i5_cache")
        reference.pop("rtl/alu.sv")
        with self.assertRaisesRegex(ValueError, "rtl/alu.sv"):
            build_reference_plan(reference)

    def test_resume_mode_change_regenerates_all_files_and_updates_provenance(self):
        self.runtime.options["use_l1_reference"] = False
        reference_plan = dict(self.model_plan, implementation_source="reference")
        self.runtime.write_json_artifact("plan.json", reference_plan)
        def call_model(event, messages, **kwargs):
            return {'answer': json.dumps({'files': [
                {'path': m['file'], 'content': f"module {m['name']}; endmodule"}
                for m in self.model_plan['modules']]})}
        with patch.object(self.runtime, "call_model_messages", side_effect=call_model) as model:
            out = CoderAgent(self.runtime).run(self.handoff,
                existing_files={"rtl/rv32i5.sv": "reference contents"}, start_module="extra")
        artifacts = self.runtime.read_handoff(out)["payload"]["artifacts"]
        self.assertEqual(model.call_count, 1)
        self.assertEqual(artifacts["plan"], "artifacts/plan_model_resume.json")
        self.assertEqual(self.runtime.read_json_artifact(artifacts["plan"])["implementation_source"], "model")
        entries = self.runtime.read_json_artifact(artifacts["rtl_manifest"])["files"]
        self.assertEqual({entry["implementation"] for entry in entries}, {"model"})

    def test_disable_reference_does_not_mix_with_model(self):
        self.runtime.options["use_l1_reference"] = False
        def call_model(event, messages, **kwargs):
            return {'answer': json.dumps({'files': [
                {'path': m['file'], 'content': f"module {m['name']}; endmodule"}
                for m in self.model_plan['modules']]})}
        with patch.object(self.runtime, "call_model_messages", side_effect=call_model) as model:
            out = CoderAgent(self.runtime).run(self.handoff)
        artifacts = self.runtime.read_handoff(out)["payload"]["artifacts"]
        self.assertEqual(artifacts["plan"], "artifacts/plan.json")
        files = self.runtime.read_json_artifact(artifacts["rtl_manifest"])["files"]
        self.assertEqual(model.call_count, 1)
        self.assertEqual({entry["implementation"] for entry in files}, {"model"})
        self.assertEqual({entry["path"] for entry in files}, {"rtl/rv32i5.sv", "rtl/extra.sv"})


if __name__ == "__main__":
    unittest.main()
