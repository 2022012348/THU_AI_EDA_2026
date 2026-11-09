"""Reference planning must match actual RTL and avoid an unused model call."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.planner import PlannerAgent, duplicate_interface_ports


class ReferencePlannerTests(unittest.TestCase):
    def test_duplicate_planned_input_and_output_are_detected(self):
        plan = {'modules': [{'name': 'mem_stage', 'interfaces':
                 'input logic [4:0] rd; output logic [4:0] rd; input logic clk'},
                {'name': 'other', 'interfaces': 'input logic rd; output logic next_rd'}]}
        self.assertEqual(duplicate_interface_ports(plan), ['mem_stage: duplicate port rd'])

    def test_reference_plan_is_complete_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            def begin(node_id, node_type, title, prompt, attempt=1):
                event = {"step": 1, "node_id": node_id, "title": title}
                events.append(event)
                return event
            def finish(event, status, **fields):
                event.update(status=status, **fields)
            runtime = RunContext(run_dir=Path(tmp), options={"project": {"id": "rv32i5_cache"}, "use_l1_reference": True},
                                 begin_event=begin, finish_event=finish, persist=lambda *a: None,
                                 emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            spec = runtime.write_text_artifact("spec.md", "L1 spec")
            handoff = runtime.write_handoff("parser", "planner", {"artifacts": {"spec": spec}})
            with patch.object(runtime, "call_model", side_effect=AssertionError("unneeded planner model call")):
                out = PlannerAgent(runtime).run(handoff)
            plan_ref = runtime.read_handoff(out)["payload"]["artifacts"]["plan"]
            plan = runtime.read_json_artifact(plan_ref)
            self.assertIn("alu", {m["name"] for m in plan["modules"]})
            self.assertEqual(events[0]["implementation"], "reference")
            self.assertEqual(plan["implementation_source"], "reference")
