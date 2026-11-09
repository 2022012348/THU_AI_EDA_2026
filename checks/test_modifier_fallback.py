"""Modifier evidence handoff and exact edit recovery regressions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent import orchestrator
from ai_eda.agent.orchestrator import _seed_modifier_input
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.modifier import ModifierAgent, _apply_exact_edits, _validated_evidence


class EvidenceTests(unittest.TestCase):
    def test_only_snapshot_matched_and_sourced_evidence_is_accepted(self):
        text = 'module a; endmodule'
        digest = hashlib.sha256(text.encode()).hexdigest()
        good = {'source': 'Icarus directed test, run abc, stdout line 12',
                'observation': 'requested word0, observed word3', 'file_hashes': {'rtl/a.sv': digest}}
        data = {'schema': 'ai_eda.diagnostic_evidence.v1', 'items': [good,
                 {**good, 'source': ''}, {**good, 'file_hashes': {'rtl/a.sv': '0' * 64}},
                 {**good, 'file_hashes': {'rtl/a.sv': digest, 'rtl/other.sv': digest}}]}
        accepted, rejected = _validated_evidence(data, {'rtl/a.sv': text})
        self.assertEqual(accepted, [good])
        self.assertEqual(len(rejected), 3)


    def test_resume_explicit_evidence_overrides_and_old_evidence_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'old'
            new = Path(tmp) / 'new'
            old.mkdir()
            new.mkdir()
            def ctx_at(path):
                return RunContext(run_dir=path, options={}, begin_event=lambda *a: {},
                                  finish_event=lambda *a, **k: None, persist=lambda *a: None,
                                  emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            source_ctx = ctx_at(old)
            report_ref = source_ctx.write_json_artifact('report.json', {'passed': False})
            evidence_ref = source_ctx.write_json_artifact('evidence.json', {'value': 'old'})
            source_ctx.write_handoff('tester', 'modifier', {'artifacts': {'report': report_ref,
                                      'diagnostic_evidence': evidence_ref}}, attempt=1)
            source = {'source': old, 'run_id': 'old'}
            ctx = ctx_at(new)
            explicit = ctx.write_json_artifact('explicit.json', {'value': 'new'})
            ctx.options['diagnostic_evidence_ref'] = explicit
            handoff = _seed_modifier_input(ctx, source, 'spec', 'plan', 'manifest')
            self.assertEqual(ctx.read_handoff(handoff)['payload']['artifacts']['diagnostic_evidence'], explicit)
            other = Path(tmp) / 'other'
            other.mkdir()
            ctx2 = ctx_at(other)
            handoff2 = _seed_modifier_input(ctx2, source, 'spec', 'plan', 'manifest')
            copied = ctx2.read_handoff(handoff2)['payload']['artifacts']['diagnostic_evidence']
            self.assertEqual(ctx2.read_json_artifact(copied), {'value': 'old'})


    def test_interrupted_tester_resume_carries_evidence_from_previous_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'old'
            old.mkdir()
            ctx = RunContext(run_dir=old, options={}, begin_event=lambda *a: {},
                             finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            ctx.write_text_artifact('spec.md', 'spec')
            plan_ref = ctx.write_json_artifact('plan.json', {'modules': [{'name': 'a', 'file': 'rtl/a.sv'}]})
            manifest_ref = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest({'rtl/a.sv': 'module a; endmodule'}, 'coder'))
            evidence = {'schema': 'ai_eda.diagnostic_evidence.v1', 'items': []}
            evidence_ref = ctx.write_json_artifact('evidence.json', evidence)
            ctx.write_handoff('coder', 'tester', {'artifacts': {'plan': plan_ref, 'rtl_manifest': manifest_ref}})
            ctx.write_handoff('tester', 'modifier', {'artifacts': {'plan': plan_ref, 'rtl_manifest': manifest_ref,
                                      'diagnostic_evidence': evidence_ref}}, attempt=1)
            ctx.write_handoff('modifier', 'tester', {'artifacts': {'plan': plan_ref, 'rtl_manifest': manifest_ref}}, attempt=1)
            (old / 'events.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'events':
                                            [{'node_id': 'tester', 'attempt': 2, 'status': 'running'}]}))
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                self.assertEqual(orchestrator._load_resume_source('old')['diagnostic_evidence'], evidence)


class ExactEditTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'modules': [{'name': 'a', 'file': 'rtl/a.sv'}]}
        self.files = {'rtl/a.sv': 'module a;\nassign x = 0;\nendmodule\n'}

    def test_apply_and_reject_ambiguous_or_out_of_scope(self):
        edit = {'path': 'rtl/a.sv', 'before': 'assign x = 0;', 'after': 'assign x = 1;'}
        changed = _apply_exact_edits({'edits': [edit]}, self.plan, self.files)
        self.assertIn('assign x = 1;', changed['rtl/a.sv'])
        for invalid in [
            {**edit, 'path': '../outside.sv'},
            {**edit, 'before': 'not present'},
            {**edit, 'after': ''},
            {**edit, 'after': edit['before']},
            {**edit, 'before': 'a'},  # appears multiple times
        ]:
            with self.assertRaises(ValueError):
                _apply_exact_edits({'edits': [invalid]}, self.plan, self.files)
        # Count overlapping occurrences too: 'aa' occurs twice in 'aaa'.
        with self.assertRaises(ValueError):
            _apply_exact_edits({'edits': [{**edit, 'before': 'aa'}]}, self.plan,
                               {'rtl/a.sv': 'module aaa; endmodule'})
        self.assertEqual(self.files['rtl/a.sv'], 'module a;\nassign x = 0;\nendmodule\n')

    def test_history_budget_drops_old_full_snapshots_but_keeps_current(self):
        agent = object.__new__(ModifierAgent)
        agent.MAX_HISTORY_CHARS = 20
        history = [
            {'role': 'system', 'content': 'system'},
            {'role': 'user', 'content': 'frozen spec'},
            {'role': 'assistant', 'content': 'old patch'},
            {'role': 'user', 'content': 'old snapshot' * 10},
            {'role': 'assistant', 'content': 'latest patch'},
            {'role': 'user', 'content': 'current snapshot'},
        ]
        trimmed = agent._trim_history(history)
        self.assertEqual([m['role'] for m in trimmed], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(trimmed[1]['content'], 'frozen spec')
        self.assertEqual(trimmed[-1]['content'], 'current snapshot')
        self.assertNotIn(history[3], trimmed)

    def test_two_noops_trigger_exact_edit_and_save_every_call(self):
        source = self.files['rtl/a.sv']
        hashes = {'rtl/a.sv': hashlib.sha256(source.encode()).hexdigest()}
        evidence = {'schema': 'ai_eda.diagnostic_evidence.v1', 'items': [
            {'source': 'directed test with retained stdout', 'observation': 'x should be 1', 'file_hashes': hashes}]}
        class Client:
            def __init__(self):
                self.call = 0
                self.messages = []
            def stream_chat_detail(self, messages):
                self.messages.append(messages)
                self.call += 1
                if self.call <= 2:
                    answer = {'files': [{'path': 'rtl/a.sv', 'content': source}], 'notes': 'no change'}
                else:
                    answer = {'edits': [{'path': 'rtl/a.sv', 'before': 'assign x = 0;', 'after': 'assign x = 1;'}], 'notes': 'correct x'}
                yield {'type': 'done', 'answer': json.dumps(answer), 'finish_reason': 'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            def begin(*args):
                event = {'step': 1, 'node_id': 'modifier'}
                events.append(event)
                return event
            ctx = RunContext(run_dir=root, options={'project': {'id': 'rv32i5'}},
                             begin_event=begin, finish_event=lambda *a, **k: None,
                             persist=lambda *a: None, emit=lambda *a: None,
                             check_cancel=lambda: None, request_input=None)
            client = Client()
            ctx.make_client = lambda *a: client
            spec_ref = ctx.write_text_artifact('spec.md', 'required behavior')
            plan_ref = ctx.write_json_artifact('plan.json', self.plan)
            manifest_ref = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest(self.files, 'coder'))
            report_ref = ctx.write_json_artifact('report.json', {'passed': False, 'stage': 'simulation',
                                                                  'checks': [{'name': 'fail', 'detail': 'x wrong'}]})
            evidence_ref = ctx.write_json_artifact('diagnostic_evidence.json', evidence)
            handoff = ctx.write_handoff('tester', 'modifier', {'artifacts': {'spec': spec_ref, 'plan': plan_ref,
                                      'rtl_manifest': manifest_ref, 'report': report_ref, 'diagnostic_evidence': evidence_ref}}, attempt=1)
            output = ModifierAgent(ctx).run(handoff, 1)
            self.assertEqual(client.call, 3)
            self.assertIn('x should be 1', json.dumps(client.messages[0], ensure_ascii=False))
            self.assertIn('x should be 1', json.dumps(client.messages[2], ensure_ascii=False))
            self.assertEqual(events[0]['repair_fallback'], 'exact_text_edits')
            manifest = ctx.read_json_artifact(ctx.read_handoff(output)['payload']['artifacts']['rtl_manifest'])
            self.assertIn('assign x = 1;', ctx.read_text_artifact(manifest['files'][0]['artifact']))
            self.assertEqual(len(list((root / 'step-01-modifier').glob('call-*'))), 3)
            # After a repair changes the hashed file, the old observation must
            # not reappear in the persistent conversation on the next round.
            self.assertNotIn('x should be 1', json.dumps(ModifierAgent(ctx).context['conversation'], ensure_ascii=False))
            current = ctx.read_text_artifact(manifest['files'][0]['artifact'])
            class SecondClient:
                def __init__(self):
                    self.messages = []
                def stream_chat_detail(self, messages):
                    self.messages.append(messages)
                    answer = {'files': [{'path': 'rtl/a.sv', 'content': current.replace('x = 1', 'x = 2')}], 'notes': 'second'}
                    yield {'type': 'done', 'answer': json.dumps(answer), 'finish_reason': 'stop'}
            second = SecondClient()
            ctx.make_client = lambda *a: second
            next_handoff = ctx.write_handoff('tester', 'modifier', {'artifacts': {'spec': spec_ref, 'plan': plan_ref,
                                  'rtl_manifest': ctx.read_handoff(output)['payload']['artifacts']['rtl_manifest'],
                                  'report': report_ref, 'diagnostic_evidence': evidence_ref}}, attempt=2)
            ModifierAgent(ctx).run(next_handoff, 2)
            self.assertNotIn('x should be 1', json.dumps(second.messages, ensure_ascii=False))
            self.assertEqual(events[-1]['diagnostic_evidence']['accepted'], 0)
            self.assertTrue(events[-1]['diagnostic_evidence']['rejected'])


if __name__ == '__main__':
    unittest.main()
