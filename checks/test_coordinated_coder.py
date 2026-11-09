import json
import tempfile
import unittest
from pathlib import Path

from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.coder import CoderAgent


class CoordinatedCoderTests(unittest.TestCase):
    def test_complete_project_is_generated_and_snapshotted_as_model_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, events = [], []
            expected = {'rtl/core.sv': 'module core(input logic clk); helper h(.clk(clk)); endmodule',
                        'rtl/helper.sv': 'module helper(input logic clk); endmodule'}
            def begin(node, kind, title, prompt, attempt=1):
                event = {'step': len(events) + 1, 'node_id': node}
                events.append(event)
                return event
            ctx = RunContext(run_dir=Path(tmp), options={'project': {'id': 'rv32i5_cache'}, 'use_l1_reference': False},
                             begin_event=begin, finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            class Client:
                def stream_chat_detail(self, messages):
                    calls.append(messages)
                    # Incomplete output must be returned to the model, without
                    # writing a half-project to the workspace.
                    self.assert_no_partial()
                    paths = list(expected) if len(calls) > 1 else ['rtl/core.sv']
                    yield {'type': 'done', 'answer': json.dumps({'files': [
                        {'path': p, 'content': expected[p]} for p in paths]}), 'finish_reason': 'stop'}
                def assert_no_partial(self):
                    if (Path(tmp) / 'project/rtl/core.sv').exists():
                        raise AssertionError('incomplete model response was written')
            ctx.make_client = lambda *a: Client()
            spec = ctx.write_text_artifact('spec.md', 'original spec')
            plan = ctx.write_json_artifact('plan.json', {'top_module': 'core', 'modules': [
                {'name': 'core', 'file': 'rtl/core.sv', 'description': 'top', 'interfaces': 'input logic clk'},
                {'name': 'helper', 'file': 'rtl/helper.sv', 'description': 'helper', 'interfaces': 'input logic clk'}]})
            incoming = ctx.write_handoff('planner', 'coder', {'artifacts': {'spec': spec, 'plan': plan}})
            out = CoderAgent(ctx).run(incoming)
            self.assertEqual(len(calls), 2)
            manifest_ref = ctx.read_handoff(out)['payload']['artifacts']['rtl_manifest']
            manifest = ctx.read_json_artifact(manifest_ref)
            self.assertEqual({f['path'] for f in manifest['files']}, set(expected))
            self.assertEqual({f['implementation'] for f in manifest['files']}, {'model'})
            self.assertEqual(events[0]['generation_mode'], 'coordinated')
            for path, rtl in expected.items():
                self.assertEqual((Path(tmp) / 'project' / path).read_text(), rtl)
