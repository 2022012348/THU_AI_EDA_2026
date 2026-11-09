"""Effective internal RTL interfaces must track changed RTL, not model notes."""
import json
import tempfile
import unittest
from pathlib import Path

from ai_eda.agent.rtl_contracts import extract_module_header, reconcile_plan_interfaces
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.modifier import ModifierAgent


TOP = 'module top(input logic clk, output logic out); child u(.clk(clk), .out(out)); endmodule\n'
CHILD = 'module child(input logic clk, output logic out); assign out = clk; endmodule\n'
CHILD_CHANGED = 'module child(input logic clk, input logic stall, output logic out); assign out = clk & !stall; endmodule\n'
TOP_CHANGED = 'module top(input logic clk, output logic out); child u(.clk(clk), .stall(1\'b0), .out(out)); endmodule\n'
PLAN = {'top_module': 'top', 'modules': [{'name': 'top', 'file': 'rtl/top.sv', 'interfaces': 'natural language'},
                                      {'name': 'child', 'file': 'rtl/child.sv', 'interfaces': 'not parsed by test'}]}


class ContractTests(unittest.TestCase):
    def test_modifier_retries_invalid_internal_header_before_writing(self):
        class Client:
            def __init__(self):
                self.calls = 0
                self.feedback = ''
            def stream_chat_detail(self, messages):
                self.calls += 1
                if self.calls == 1:
                    content = 'module child(input logic clk, input logic out, output logic out); endmodule'
                else:
                    self.feedback = messages[-1]['content']
                    content = CHILD_CHANGED
                payload = {'files': [{'path': 'rtl/child.sv', 'content': content}], 'notes': ''}
                yield {'type': 'done', 'answer': json.dumps(payload), 'finish_reason': 'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(run_dir=Path(tmp), options={'project': {'id': 'stream_filter'}},
                             begin_event=lambda *a: {'step': 1, 'node_id': 'modifier'},
                             finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            client = Client()
            ctx.make_client = lambda *a: client
            files = {'rtl/top.sv': TOP, 'rtl/child.sv': CHILD}
            spec = ctx.write_text_artifact('spec.md', 'spec')
            plan = ctx.write_json_artifact('plan.json', PLAN)
            manifest = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest(files, 'coder'))
            report = ctx.write_json_artifact('report.json', {'passed': False, 'stage': 'compile'})
            handoff = ctx.write_handoff('tester', 'modifier', {'artifacts': {'spec': spec, 'plan': plan,
                                                                         'rtl_manifest': manifest, 'report': report}}, attempt=1)
            ModifierAgent(ctx).run(handoff, 1)
            self.assertEqual(client.calls, 2)
            self.assertIn('端口名称缺失或重复', client.feedback)
            self.assertEqual((Path(tmp) / 'project/rtl/child.sv').read_text(), CHILD_CHANGED)

    def test_repair_duplicate_internal_ports_requires_valid_replacement(self):
        bad = 'module child(input logic clk, input logic out, output logic out); endmodule'
        files = {'rtl/top.sv': TOP, 'rtl/child.sv': bad}
        updated, changed = reconcile_plan_interfaces(PLAN, files, {'rtl/child.sv': CHILD})
        self.assertEqual(changed, ['rtl/child.sv'])
        self.assertIn('output logic out', updated['modules'][1]['interfaces'])
        with self.assertRaises(ValueError):
            reconcile_plan_interfaces(PLAN, files, {'rtl/child.sv': bad})
        with self.assertRaises(ValueError):
            reconcile_plan_interfaces(PLAN, {'rtl/top.sv': bad.replace('child', 'top')}, {'rtl/top.sv': TOP})

    def test_internal_change_updates_plan_and_keeps_input_unchanged(self):
        updated, changed = reconcile_plan_interfaces(PLAN, {'rtl/top.sv': TOP, 'rtl/child.sv': CHILD},
                                                       {'rtl/top.sv': TOP_CHANGED, 'rtl/child.sv': CHILD_CHANGED})
        self.assertEqual(changed, ['rtl/child.sv'])
        self.assertIn('input logic stall', updated['modules'][1]['interfaces'])
        self.assertEqual(PLAN['modules'][1]['interfaces'], 'not parsed by test')
        self.assertEqual(updated['modules'][0]['interfaces'], 'natural language')

    def test_external_interface_change_or_unparseable_header_is_rejected(self):
        original = {'rtl/top.sv': TOP, 'rtl/child.sv': CHILD}
        for replacement in [TOP.replace('output logic out', 'output logic [1:0] out'),
                            'module wrong(input clk); endmodule', 'module top(input clk; endmodule']:
            with self.assertRaises(ValueError):
                reconcile_plan_interfaces(PLAN, original, {'rtl/top.sv': replacement})
        with self.assertRaises(ValueError):
            extract_module_header('module child(clk, out); input clk; output out; endmodule', 'child')

    def test_valid_continuation_ports_and_parameters(self):
        h = extract_module_header('module a #(parameter N=3) (input logic [N-1:0] a, b, output logic out); endmodule', 'a')
        self.assertIn('b', h['interfaces'])
        self.assertIn('N=3', h['parameters'])

    def test_modifier_handoff_uses_new_plan_without_overwriting_original(self):
        class Client:
            def stream_chat_detail(self, messages):
                result = {'files': [{'path': 'rtl/top.sv', 'content': TOP_CHANGED},
                                    {'path': 'rtl/child.sv', 'content': CHILD_CHANGED}], 'notes': 'no port changes'}
                yield {'type': 'done', 'answer': json.dumps(result), 'finish_reason': 'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            def begin(*args):
                event = {'step': 1, 'node_id': 'modifier'}
                events.append(event)
                return event
            ctx = RunContext(run_dir=root, options={'project': {'id': 'stream_filter'}},
                             begin_event=begin, finish_event=lambda *a, **k: None,
                             persist=lambda *a: None, emit=lambda *a: None,
                             check_cancel=lambda: None, request_input=None)
            ctx.make_client = lambda *a: Client()
            files = {'rtl/top.sv': TOP, 'rtl/child.sv': CHILD}
            spec = ctx.write_text_artifact('spec.md', 'spec')
            plan = ctx.write_json_artifact('plan.json', PLAN)
            manifest = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest(files, 'coder'))
            report = ctx.write_json_artifact('report.json', {'passed': False, 'stage': 'simulation'})
            handoff = ctx.write_handoff('tester', 'modifier', {'artifacts': {'spec': spec, 'plan': plan,
                                                                         'rtl_manifest': manifest, 'report': report}}, attempt=1)
            result = ModifierAgent(ctx).run(handoff, 1)
            new_ref = ctx.read_handoff(result)['payload']['artifacts']['plan']
            self.assertEqual(new_ref, 'artifacts/plan_attempt1.json')
            self.assertIn('input logic stall', ctx.read_json_artifact(new_ref)['modules'][1]['interfaces'])
            self.assertEqual(ctx.read_json_artifact(plan), PLAN)
            self.assertEqual(events[0]['interface_changes'], ['rtl/child.sv'])


if __name__ == '__main__':
    unittest.main()
