import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.modifier import ModifierAgent, repair_effect


class IndependentReviewTests(unittest.TestCase):
    def test_halt_timeout_does_not_hide_regressions_as_improvements(self):
        previous = {'stage': 'simulation', 'checks': [
            {'name': 'bench', 'detail': 'x10 wrong'}, {'name': 'alu', 'detail': 'x2 wrong'}]}
        current = {'stage': 'simulation', 'checks': [
            {'name': 'bench', 'detail': '等待 halted 超时（5000 周期）'}]}
        effect = repair_effect(previous, current)
        self.assertEqual(effect['completion_regressions'], ['bench'])
        self.assertEqual(effect['no_longer_reported'], [('alu', 'x2 wrong')])
        self.assertEqual(effect['unverified_disappearances'], [('bench', 'x10 wrong')])

    def test_effect_does_not_call_missing_checks_fixed_on_timeout(self):
        previous = {'stage': 'simulation', 'checks': [{'name': 'load', 'detail': 'wrong'}]}
        timed = {'stage': 'simulation', 'timed_out': True, 'checks': [{'name': 'simulation_timeout'}]}
        effect = repair_effect(previous, timed)
        self.assertFalse(effect['comparable'])
        self.assertEqual(effect['no_longer_reported'], [])
        effect = repair_effect(previous, {'stage': 'simulation', 'checks': []})
        self.assertTrue(effect['comparable'])
        self.assertEqual(effect['no_longer_reported'], [('load', 'wrong')])

    def test_repeated_failure_uses_fresh_model_review_for_current_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, calls = [], []
            def begin(node, kind, title, prompt, attempt=1):
                event = {'step': len(events) + 1, 'node_id': node}
                events.append(event)
                return event
            ctx = RunContext(run_dir=Path(tmp), options={'project': {'id': 'rv32i5_cache'}},
                             begin_event=begin, finish_event=lambda *a, **k: None,
                             persist=lambda *a: None, emit=lambda *a: None,
                             check_cancel=lambda: None, request_input=None)
            class Client:
                def stream_chat_detail(self, messages):
                    calls.append(messages)
                    if 'independent RTL failure analyst' in messages[0]['content']:
                        answer = 'Review the current ready/valid dependency.'
                    else:
                        answer = json.dumps({'files': [{'path': 'rtl/core.sv', 'content':
                            f'module core; wire unused_{len(calls)}; endmodule'}], 'notes': 'model repair'})
                    yield {'type': 'done', 'answer': answer, 'finish_reason': 'stop'}
            ctx.make_client = lambda *a: Client()
            files = {'rtl/core.sv': 'module core; endmodule'}
            spec = ctx.write_text_artifact('spec.md', 'Frozen specification')
            plan = ctx.write_json_artifact('plan.json', {'top_module': 'core', 'modules': [
                {'name': 'core', 'file': 'rtl/core.sv', 'interfaces': ''}]})
            report = ctx.write_json_artifact('report.json', {'passed': False, 'stage': 'simulation',
                'checks': [{'name': 'case', 'detail': 'bad result'}]})
            agent = ModifierAgent(ctx)
            reviewed_source = None
            for attempt in range(1, 4):
                if attempt == 2:
                    reviewed_source = files['rtl/core.sv']
                manifest = ctx.write_json_artifact(f'manifest{attempt}.json', ctx.snapshot_rtl_manifest(files, f'round{attempt}'))
                incoming = ctx.write_handoff('tester', 'modifier', {'artifacts': {
                    'spec': spec, 'plan': plan, 'rtl_manifest': manifest, 'report': report}}, attempt=attempt)
                agent.run(incoming, attempt)
                files['rtl/core.sv'] = (Path(tmp) / 'project/rtl/core.sv').read_text()
            review_calls = [c for c in calls if 'independent RTL failure analyst' in c[0]['content']]
            self.assertEqual(len(review_calls), 1)
            # Every normal repair round starts from current evidence, rather
            # than resending a chain of old full RTL snapshots and patches.
            self.assertEqual(len(calls[2]), 2)
            self.assertIn('Tester 对上轮已应用修改的实际反馈', calls[2][-1]['content'])
            self.assertEqual(len(review_calls[0]), 2)
            self.assertIn(reviewed_source, review_calls[0][-1]['content'])
            artifact = ctx.read_json_artifact('artifacts/independent_review_attempt2.json')
            self.assertEqual(artifact['source'], 'model')
            self.assertEqual(artifact['file_hashes']['rtl/core.sv'], hashlib.sha256(reviewed_source.encode()).hexdigest())
            self.assertIn('Review the current ready/valid dependency.', calls[2][-1]['content'])
            self.assertEqual(calls[2][-1]['content'].count('Frozen specification'), 1)

    def test_bounded_probe_planning_truncation_is_not_a_diagnosis_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            events=[]; options=[]
            def begin(node,kind,title,prompt,attempt=1):
                e={'step':len(events)+1,'node_id':node};events.append(e);return e
            ctx=RunContext(run_dir=Path(tmp),options={},begin_event=begin,
                finish_event=lambda *a,**k:None,persist=lambda *a:None,
                emit=lambda *a:None,check_cancel=lambda:None,request_input=None)
            class Client:
                def stream_chat_detail(self,messages):
                    yield {'type':'done','answer':'{"hypotheses":["unfinished', 'finish_reason':'length'}
            def make(overrides=None):options.append(overrides);return Client()
            ctx.make_client=make
            result=ModifierAgent(ctx)._independent_review('frozen',{'top_module':'core'},
                {'rtl/core.sv':'module core; endmodule'}, {'stage':'simulation','checks':[]},1)
            self.assertEqual(ctx.model_calls,1)
            self.assertFalse(options[0]['thinking'])
            self.assertEqual(options[0]['max_tokens'],3000)
            self.assertIn('no completed diagnosis',result)
            self.assertNotIn('unfinished',result)
            review=ctx.read_json_artifact('artifacts/independent_review_attempt1.json')
            self.assertEqual(review['status'],'truncated')
