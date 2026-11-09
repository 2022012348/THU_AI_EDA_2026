"""Select a verified historical Tester failure without changing its run."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_eda.agent import orchestrator
from ai_eda.agent.subagents.base import RunContext


def context(root):
    return RunContext(run_dir=root, options={}, begin_event=lambda *a: {},
                      finish_event=lambda *a, **k: None, persist=lambda *a: None,
                      emit=lambda *a: None, check_cancel=lambda: None, request_input=None)


def build_run(source):
    ctx = context(source)
    original = 'module core; wire a = 0; endmodule\n'
    changed = 'module core; wire a = 1; endmodule\n'
    spec1 = ctx.write_text_artifact('spec_first.md', 'spec first')
    spec2 = ctx.write_text_artifact('spec_second.md', 'spec second')
    plan1 = ctx.write_json_artifact('plan_first.json', {'top_module': 'core', 'version': 1,
                                   'modules': [{'name': 'core', 'file': 'rtl/core.sv'}]})
    plan2 = ctx.write_json_artifact('plan_second.json', {'top_module': 'core', 'version': 2,
                                   'modules': [{'name': 'core', 'file': 'rtl/core.sv'}]})
    ctx.write_text_artifact('spec.md', 'latest spec')
    ctx.write_json_artifact('plan.json', {'top_module': 'core', 'version': 9,
                            'modules': [{'name': 'core', 'file': 'rtl/core.sv'}]})
    man1 = ctx.write_json_artifact('manifest1.json', ctx.snapshot_rtl_manifest({'rtl/core.sv': original}, 'first'))
    man2 = ctx.write_json_artifact('manifest2.json', ctx.snapshot_rtl_manifest({'rtl/core.sv': changed}, 'second'))
    report1 = ctx.write_json_artifact('report1.json', {'passed': False, 'stage': 'simulation', 'round': 1})
    report2 = ctx.write_json_artifact('report2.json', {'passed': False, 'stage': 'simulation', 'round': 2})
    evidence = {'schema': 'ai_eda.diagnostic_evidence.v1', 'items': [
        {'source': 'test one', 'observation': 'first snapshot only', 'file_hashes': {'rtl/core.sv': hashlib.sha256(original.encode()).hexdigest()}},
        {'source': 'test two', 'observation': 'second snapshot only', 'file_hashes': {'rtl/core.sv': hashlib.sha256(changed.encode()).hexdigest()}}]}
    evidence_ref = ctx.write_json_artifact('evidence.json', evidence)
    for n, spec, plan, manifest, report in [(1, spec1, plan1, man1, report1), (2, spec2, plan2, man2, report2)]:
        ctx.write_handoff('tester', 'modifier', {'attempt': n, 'artifacts': {
            'spec': spec, 'plan': plan, 'rtl_manifest': manifest, 'report': report,
            'diagnostic_evidence': evidence_ref}}, attempt=n)
    (source / 'events.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'status': 'failed',
        'events': [{'node_id': 'tester', 'attempt': 1, 'status': 'failed'},
                   {'node_id': 'tester', 'attempt': 2, 'status': 'failed'},
                   {'node_id': 'modifier', 'status': 'failed'}]}))
    (source / 'metadata.json').write_text(json.dumps({'project_id': 'rv32i5_cache', 'use_l1_reference': False}))
    (source / 'agents/modifier').mkdir(parents=True)
    (source / 'agents/modifier/context.json').write_text(json.dumps({'notes': 'later unrelated', 'failing_tests': ['later']}))
    return original, changed


class ResumeRoundTests(unittest.TestCase):
    def test_select_specific_snapshot_plan_report_and_matching_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'original'
            source.mkdir()
            original, changed = build_run(source)
            before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                first = orchestrator._load_resume_source('original', tester_attempt=1)
                second = orchestrator._load_resume_source('original', tester_attempt=2)
                self.assertEqual(first['stage'], 'modifier')
                self.assertEqual(first['project_files']['rtl/core.sv'], original)
                self.assertEqual(first['plan']['version'], 1)
                self.assertEqual(first['spec'], 'spec first')
                self.assertEqual([i['source'] for i in first['diagnostic_evidence']['items']], ['test one'])
                self.assertEqual(second['project_files']['rtl/core.sv'], changed)
                self.assertEqual(second['plan']['version'], 2)
                self.assertEqual([i['source'] for i in second['diagnostic_evidence']['items']], ['test two'])
                captured = {}
                def capture(agent, handoff, attempt):
                    incoming = agent.runtime.read_handoff(handoff)['payload']
                    captured['report'] = agent.runtime.read_json_artifact(incoming['artifacts']['report'])
                    captured['source_attempt'] = incoming['source_tester_attempt']
                    captured['context'] = dict(agent.context)
                    captured['plan'] = agent.runtime.read_json_artifact(incoming['artifacts']['plan'])
                    captured['evidence'] = agent.runtime.read_json_artifact(incoming['artifacts']['diagnostic_evidence'])
                    raise RuntimeError('stop after inspection')
                with patch.object(orchestrator.ModifierAgent, 'run', new=capture):
                    with self.assertRaisesRegex(RuntimeError, 'stop after inspection'):
                        orchestrator.run_agent(project_id='rv32i5_cache', use_l1_reference=False,
                                               resume_from='original', resume_tester_attempt=1)
            self.assertEqual(captured['report']['round'], 1)
            self.assertEqual(captured['plan']['version'], 1)
            self.assertEqual(captured['source_attempt'], 1)
            self.assertNotIn('notes', captured['context'])
            self.assertEqual([i['source'] for i in captured['evidence']['items']], ['test one'])
            self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_selected_handoff_does_not_depend_on_latest_spec_or_coder_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'original'
            source.mkdir()
            build_run(source)
            (source / 'artifacts/spec.md').unlink()
            (source / 'artifacts/plan.json').unlink()
            (source / 'handoffs/coder_to_tester.json').write_text('{"payload":{"artifacts":{"plan":"missing.json"}}}')
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                resume = orchestrator._load_resume_source('original', tester_attempt=1)
            self.assertEqual(resume['spec'], 'spec first')
            self.assertEqual(resume['plan']['version'], 1)

    def test_reject_missing_round_tampered_snapshot_and_mutable_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'original'
            source.mkdir()
            build_run(source)
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, '没有第 3 轮'):
                    orchestrator._load_resume_source('original', tester_attempt=3)
                manifest_file = source / 'artifacts/manifest1.json'
                manifest = json.loads(manifest_file.read_text())
                path = source / manifest['files'][0]['artifact']
                path.write_text('tampered')
                with self.assertRaisesRegex(ValueError, '不可变 RTL 快照'):
                    orchestrator._load_resume_source('original', tester_attempt=1)
                manifest['files'][0]['artifact'] = 'project/rtl/core.sv'
                (source / 'project/rtl').mkdir(parents=True)
                (source / 'project/rtl/core.sv').write_text('latest mutable')
                manifest_file.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, '不可变 RTL 快照'):
                    orchestrator._load_resume_source('original', tester_attempt=1)

    def test_reject_unmatched_plan_or_passed_report_and_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'original'
            source.mkdir()
            build_run(source)
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, '必须与 resume_from'):
                    orchestrator.run_agent(resume_tester_attempt=1)
                report = source / 'artifacts/report1.json'
                report.write_text(json.dumps({'passed': True}))
                with self.assertRaisesRegex(ValueError, '失败报告'):
                    orchestrator._load_resume_source('original', tester_attempt=1)
                report.write_text(json.dumps({'passed': False}))
                (source / 'artifacts/plan_first.json').write_text(json.dumps({'modules': [{'name': 'other', 'file': 'rtl/other.sv'}]}))
                with self.assertRaisesRegex(ValueError, '文件清单不一致'):
                    orchestrator._load_resume_source('original', tester_attempt=1)


if __name__ == '__main__':
    unittest.main()
