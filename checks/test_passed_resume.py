"""A successful run resumes from its final successful Tester input."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_eda.agent import orchestrator
from ai_eda.agent.subagents.base import RunContext


class PassedResumeTests(unittest.TestCase):
    def test_final_passing_tester_supersedes_earlier_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'old'; source.mkdir()
            ctx = RunContext(run_dir=source, options={}, begin_event=lambda *a: {},
                             finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            ctx.write_text_artifact('spec.md', 'spec')
            plan1 = ctx.write_json_artifact('plan.json', {'modules':[{'name':'a','file':'rtl/a.sv'}], 'revision': 1})
            plan2 = ctx.write_json_artifact('plan_attempt1.json', {'modules':[{'name':'a','file':'rtl/a.sv'}], 'revision': 2})
            old = ctx.write_json_artifact('rtl_manifest.json', ctx.snapshot_rtl_manifest({'rtl/a.sv':'module a; // old\nendmodule'}, 'coder'))
            final = ctx.write_json_artifact('rtl_manifest_attempt1.json', ctx.snapshot_rtl_manifest({'rtl/a.sv':'module a; // final\nendmodule'}, 'modifier_attempt1'))
            ctx.write_handoff('coder','tester',{'artifacts':{'plan':plan1,'rtl_manifest':old}})
            ctx.write_handoff('modifier','tester',{'artifacts':{'plan':plan2,'rtl_manifest':final}},attempt=1)
            (source/'events.json').write_text(json.dumps({'status':'passed','project_id':'rv32i5_cache','events':[
                {'node_id':'tester','status':'failed','attempt':1},
                {'node_id':'modifier','status':'info','attempt':1},
                {'node_id':'tester','status':'passed','attempt':2}]}))
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)):
                loaded = orchestrator._load_resume_source('old')
            self.assertEqual(loaded['stage'], 'tester')
            self.assertEqual(loaded['plan']['revision'], 2)
            self.assertIn('// final', loaded['project_files']['rtl/a.sv'])

    def test_passed_without_successful_tester_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'old'; source.mkdir()
            ctx = RunContext(run_dir=source, options={}, begin_event=lambda *a: {},
                             finish_event=lambda *a, **k: None, persist=lambda *a: None,
                             emit=lambda *a: None, check_cancel=lambda: None, request_input=None)
            ctx.write_text_artifact('spec.md','spec'); ctx.write_json_artifact('plan.json',{'modules':[]})
            (source/'events.json').write_text(json.dumps({'status':'passed','events':[{'node_id':'tester','status':'failed'}]}))
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)):
                with self.assertRaisesRegex(ValueError,'缺少最终 Tester'):
                    orchestrator._load_resume_source('old')
