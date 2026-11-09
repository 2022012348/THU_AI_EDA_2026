import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_eda.agent import orchestrator


class CheckpointRetestTests(unittest.TestCase):
    def test_retest_runs_tester_before_any_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = {'run_id': 'source', 'source': Path(tmp), 'project_id': 'rv32i5_cache',
                      'use_l1_reference': False, 'stage': 'modifier', 'spec': 'spec',
                      'plan': {'top_module': 'core', 'modules': [{'name':'core','file':'rtl/core.sv','interfaces':'','description':''}]},
                      'project_files': {'rtl/core.sv':'module core; endmodule'}, 'parser_result': {},
                      'project_provenance': {}}
            with patch.object(orchestrator, 'AGENT_RUNS_ROOT', Path(tmp)), \
                 patch.object(orchestrator, '_load_resume_source', return_value=source), \
                 patch('ai_eda.agent.subagents.tester.test_rtl', return_value={'passed':True,'stage':'simulation','checks':[],'test_suites':[]}), \
                 patch('ai_eda.agent.subagents.tester.run_l1_icache_flush_probe', return_value={'name':'l1_icache_flush_edge','status':'passed','passed':True}), \
                 patch('ai_eda.agent.subagents.tester.run_l1_id_hazard_probe', return_value={'name':'l1_id_hazard','status':'passed','passed':True}), \
                 patch('ai_eda.agent.subagents.base.RunContext.make_client', side_effect=AssertionError('model call not expected')):
                result=orchestrator.run_agent(project_id='rv32i5_cache', use_l1_reference=False,
                    resume_from='source', resume_tester_attempt=2, resume_retest_checkpoint=True)
            self.assertTrue(result['result']['passed'])
            self.assertEqual([event['node_id'] for event in result['events']], ['tester'])
            self.assertTrue(result['result']['resume_retest_checkpoint'])

    def test_retest_requires_explicit_checkpoint(self):
        with self.assertRaisesRegex(ValueError, '指定 Tester'):
            orchestrator.run_agent(resume_retest_checkpoint=True)
