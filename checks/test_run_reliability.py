"""Regression coverage for run isolation, retries, truncation and resume."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent import orchestrator
from ai_eda.agent.subagents.base import RunContext
from ai_eda.model.client import EmptyModelResponseError


def context(root, max_calls=4):
    return RunContext(run_dir=Path(root), options={}, begin_event=lambda *a: {},
                      finish_event=lambda *a, **k: None, persist=lambda *a: None,
                      emit=lambda *a: None, check_cancel=lambda: None,
                      request_input=None, max_calls=max_calls)


class SnapshotTests(unittest.TestCase):
    def test_snapshots_preserve_each_version_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            first = ctx.snapshot_rtl_manifest({'rtl/sub/core.sv': 'module a; endmodule'}, 'coder')
            second = ctx.snapshot_rtl_manifest({'rtl/sub/core.sv': 'module b; endmodule'}, 'modifier_attempt1')
            self.assertEqual(ctx.read_text_artifact(first['files'][0]['artifact']), 'module a; endmodule')
            self.assertEqual(ctx.read_text_artifact(second['files'][0]['artifact']), 'module b; endmodule')
            self.assertNotEqual(first['files'][0]['sha256'], second['files'][0]['sha256'])
            with self.assertRaises(FileExistsError):
                ctx.snapshot_rtl_manifest({'rtl/sub/core.sv': 'different'}, 'coder')
            with self.assertRaises(ValueError):
                ctx.snapshot_rtl_manifest({'../outside.sv': 'bad'}, 'evil')

    def test_modifier_resume_uses_tested_snapshot_not_mutable_working_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'old'
            source.mkdir()
            ctx = context(source)
            (source / 'artifacts/spec.md').write_text('spec')
            ctx.write_json_artifact('plan.json', {'modules': [{'name': 'old'}]})
            plan_ref = ctx.write_json_artifact('plan_reference.json', {'modules': [{'name': 'actual'}]})
            manifest = ctx.snapshot_rtl_manifest({'rtl/core.sv': 'tested'}, 'coder')
            manifest['files'][0]['implementation'] = 'model_repair'
            manifest['files'][0]['original_implementation'] = 'model'
            manifest_ref = ctx.write_json_artifact('rtl_manifest.json', manifest)
            (source / 'project/rtl').mkdir(parents=True)
            (source / 'project/rtl/core.sv').write_text('partially modified')
            ctx.write_handoff('coder', 'tester', {'artifacts': {'plan': plan_ref, 'rtl_manifest': manifest_ref}})
            updated_plan_ref = ctx.write_json_artifact('plan_attempt1.json', {'modules': [{'name': 'updated'}]})
            ctx.write_handoff('tester', 'modifier', {'artifacts': {'plan': updated_plan_ref, 'rtl_manifest': manifest_ref}}, attempt=1)
            (source / 'events.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'events': [{'node_id': 'modifier', 'status': 'running'}]}))
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                resume = orchestrator._load_resume_source('old')
            self.assertEqual(resume['plan']['modules'][0]['name'], 'updated')
            self.assertEqual(resume['project_files']['rtl/core.sv'], 'tested')
            self.assertEqual(resume['project_provenance']['rtl/core.sv'],
                             {'implementation': 'model_repair', 'original_implementation': 'model'})
            self.assertEqual(resume['project_id'], 'rv32i5_cache')


    def test_resume_retains_diagnosis_without_reusing_stale_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / 'old'
            (source_dir / 'agents/modifier').mkdir(parents=True)
            (source_dir / 'agents/modifier/context.json').write_text(json.dumps({
                'notes': 'old failed hypothesis', 'failure_fingerprint': 'abc',
                'failing_tests': ['reset'], 'conversation': [{'role': 'user', 'content': 'stale'}],
            }))
            source = {'source': source_dir, 'run_id': 'old', 'project_id': 'rv32i5_cache', 'use_l1_reference': False,
                      'stage': 'modifier', 'spec': 'spec', 'plan': {'modules': [{'name': 'core'}]},
                      'project_files': {'rtl/core.sv': 'module core; endmodule'}, 'parser_result': {}}
            captured = {}
            def capture(agent, handoff, attempt):
                captured.update(agent.context)
                raise RuntimeError('stop after inspection')
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)), \
                 patch.object(orchestrator, '_load_resume_source', return_value=source), \
                 patch.object(orchestrator, '_seed_modifier_input', return_value=Path('unused')), \
                 patch.object(orchestrator.ModifierAgent, 'run', new=capture):
                with self.assertRaisesRegex(RuntimeError, 'stop after inspection'):
                    orchestrator.run_agent(project_id='rv32i5_cache', resume_from='old', use_l1_reference=False)
            self.assertEqual(captured['notes'], 'old failed hypothesis')
            self.assertEqual(captured['failure_fingerprint'], 'abc')
            self.assertNotIn('conversation', captured)

    def test_resume_rejects_different_project_and_generation_mode(self):
        source = {'project_id': 'rv32i5_cache', 'use_l1_reference': True}
        with patch.object(orchestrator, '_load_resume_source', return_value=source):
            with self.assertRaisesRegex(ValueError, '项目不匹配'):
                orchestrator.run_agent(project_id='rv32i5', resume_from='old')
            with self.assertRaisesRegex(ValueError, '参考实现设置'):
                orchestrator.run_agent(project_id='rv32i5_cache', resume_from='old', use_l1_reference=False)

    def test_legacy_reference_mode_inferred_only_from_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'old'
            source.mkdir()
            ctx = context(source)
            (source / 'artifacts/spec.md').write_text('spec')
            ctx.write_json_artifact('plan.json', {'modules': [{'name': 'core'}]})
            event = {'node_id': 'coder', 'status': 'failed', 'prompt': '参考实现'}
            (source / 'events.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'events': [event]}))
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                self.assertIs(orchestrator._load_resume_source('old')['use_l1_reference'], True)
            event['prompt'] = 'model prompt'
            (source / 'events.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'events': [event]}))
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                self.assertIsNone(orchestrator._load_resume_source('old')['use_l1_reference'])


class ModelReliabilityTests(unittest.TestCase):
    def test_usage_records_each_call_in_same_event(self):
        class Client:
            def stream_chat_detail(self, messages):
                yield {'type': 'done', 'answer': 'ok', 'finish_reason': 'stop',
                       'usage': {'prompt_tokens': 50, 'completion_tokens': 2, 'total_tokens': 52}}
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            ctx.make_client = lambda *a: Client()
            event = {'step': 1, 'node_id': 'modifier'}
            for _ in range(2):
                ctx.call_model_messages(event, [{'role': 'user', 'content': 'current snapshot'}])
            calls = event['model_call_usage']
            self.assertEqual([c['call_index'] for c in calls], [1, 2])
            self.assertEqual(sum(c['usage']['prompt_tokens'] for c in calls), 100)
            self.assertEqual(sum(c['output_tokens'] for c in calls), 4)
            self.assertEqual(len((Path(root) / 'model_usage.jsonl').read_text().splitlines()), 2)

    def test_reasoning_only_retry_disables_thinking(self):
        class Client:
            def __init__(self, thinking):
                self.thinking = thinking
            def stream_chat_detail(self, messages):
                if self.thinking:
                    yield {'type': 'reasoning', 'text': 'reasoning only'}
                    raise EmptyModelResponseError('empty answer', 'stop')
                yield {'type': 'done', 'answer': 'complete', 'finish_reason': 'stop'}
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            options_seen = []
            def make_client(options=None):
                options_seen.append(options)
                return Client(options is None or options.get('thinking', True))
            ctx.make_client = make_client
            event = {'step': 1, 'node_id': 'planner'}
            result = ctx.call_model_messages(event, [{'role': 'user', 'content': 'x'}])
            self.assertEqual(result['answer'], 'complete')
            self.assertEqual(options_seen, [None, {'thinking': False}])
            self.assertIs(event['empty_response_retries'][0]['retry_thinking'], False)

    def test_empty_response_retry_counts_calls_and_resets_stream(self):
        class Client:
            def __init__(self):
                self.calls = 0
            def stream_chat_detail(self, messages):
                self.calls += 1
                if self.calls == 1:
                    yield {'type': 'reasoning', 'text': 'discard old stream'}
                    raise EmptyModelResponseError('empty answer', 'stop')
                yield {'type': 'answer', 'text': 'complete'}
                yield {'type': 'done', 'answer': 'complete', 'reasoning': 'new reasoning', 'finish_reason': 'stop'}
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            ctx.make_client = lambda *a: Client()
            event = {'step': 1, 'node_id': 'coder'}
            result = ctx.call_model_messages(event, [{'role': 'user', 'content': 'x'}])
            self.assertEqual(result['answer'], 'complete')
            self.assertEqual(result['reasoning'], 'new reasoning')
            self.assertEqual(ctx.model_calls, 2)
            self.assertEqual(len(event['empty_response_retries']), 1)
            self.assertEqual([c['status'] for c in event['model_call_usage']], ['empty_response', 'completed'])

    def test_empty_retries_obey_global_call_cap(self):
        class Client:
            def stream_chat_detail(self, messages):
                raise EmptyModelResponseError('empty answer', 'stop')
                yield
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root, max_calls=1)
            ctx.make_client = lambda *a: Client()
            with self.assertRaisesRegex(ValueError, '达到上限'):
                ctx.call_model_messages({'step': 1, 'node_id': 'coder'}, [{'role': 'user', 'content': 'x'}])
            self.assertEqual(ctx.model_calls, 1)

    def test_partial_answer_with_length_is_saved_but_rejected(self):
        class Client:
            def stream_chat_detail(self, messages):
                yield {'type': 'done', 'answer': 'module partial;', 'finish_reason': 'length'}
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            ctx.make_client = lambda *a: Client()
            event = {'step': 1, 'node_id': 'coder'}
            with self.assertRaisesRegex(RuntimeError, 'finish_reason=length'):
                ctx.call_model_messages(event, [{'role': 'user', 'content': 'x'}])
            self.assertEqual((Path(root) / 'step-01-coder/raw_response.txt').read_text(), 'module partial;')
            self.assertEqual(event['finish_reason'], 'length')
            self.assertEqual(ctx.model_calls, 1)

    def test_empty_length_is_not_retried(self):
        class Client:
            def stream_chat_detail(self, messages):
                raise EmptyModelResponseError('truncated', 'length')
                yield
        with tempfile.TemporaryDirectory() as root:
            ctx = context(root)
            ctx.make_client = lambda *a: Client()
            with self.assertRaises(EmptyModelResponseError):
                ctx.call_model_messages({'step': 1, 'node_id': 'planner'}, [{'role': 'user', 'content': 'x'}])
            self.assertEqual(ctx.model_calls, 1)


if __name__ == '__main__':
    unittest.main()
