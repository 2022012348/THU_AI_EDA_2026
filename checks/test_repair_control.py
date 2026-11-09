import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ai_eda.agent.repair_control import evaluate_repair
from ai_eda.agent import orchestrator


def report(*checks, suites=None):
    return {'passed':False, 'stage':'simulation', 'checks':[{'name':n,'detail':d} for n,d in checks],
            'test_suites': suites or []}

class RepairControlTests(unittest.TestCase):
    def test_fewer_checks_with_new_timeout_is_rejected(self):
        old=report(('bench','x1 wrong'),('bench','x2 wrong'),('bench','exit wrong'))
        new=report(('bench','等待 halted 超时'))
        r=evaluate_repair(old,new)
        self.assertFalse(r['accepted'])
        self.assertIn('failed to halt',str(r['reasons']))

    def test_improvement_and_plateau_and_coverage(self):
        old=report(('a','wrong'),('b','wrong'),suites=[{'name':'core','passed':True}])
        improved=report(('a','wrong'),suites=[{'name':'core','passed':True}])
        self.assertTrue(evaluate_repair(old,improved)['accepted'])
        self.assertFalse(evaluate_repair(old,old)['accepted'])
        improved['test_suites']=[]
        self.assertFalse(evaluate_repair(old,improved)['accepted'])
        self.assertFalse(evaluate_repair(old,report(('c','wrong')))['accepted'])
        self.assertFalse(evaluate_repair(old,{'stage':'compile','checks':[]})['accepted'])
        self.assertTrue(evaluate_repair(old,{'passed':True,'stage':'simulation'})['accepted'])

    def test_real_history_does_not_treat_40_to_37_as_progress(self):
        root=Path(__file__).resolve().parents[1]/'runs/agent/agent-20261028T124412728862-4614edcbd21643008cd5e25690148489'
        if not root.exists(): self.skipTest('local historical record unavailable')
        old=json.loads((root/'tester-01/test_report.json').read_text())
        for name in ('tester-02','tester-03'):
            candidate=json.loads((root/name/'test_report.json').read_text())
            self.assertFalse(evaluate_repair(old,candidate)['accepted'])

    def test_pipeline_rolls_back_and_stops_without_losing_candidates(self):
        count=0
        class Client:
            def stream_chat_detail(self,messages):
                nonlocal count
                system=messages[0]['content']
                if 'Spec Parser' in system:
                    answer={'sufficient':True,'missing':[],'questions':[],'spec_addendum':''}
                elif 'RTL Planner' in system:
                    answer={'top_module':'core','modules':[{'name':'core','file':'rtl/core.sv','description':'core','interfaces':''}]}
                elif 'RTL Modifier' in system:
                    count+=1
                    answer={'files':[{'path':'rtl/core.sv','content':f'module core; wire candidate_{count}; endmodule'}],'notes':'model hypothesis'}
                else:
                    yield {'type':'done','answer':'module core; endmodule','finish_reason':'stop'}; return
                yield {'type':'done','answer':json.dumps(answer),'finish_reason':'stop'}
        baseline=report(('bench','x1 wrong'),('bench','x2 wrong'),('bench','exit wrong'))
        worse=report(('bench','等待 halted 超时'))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)), \
                 patch('ai_eda.agent.subagents.base.RunContext.make_client',return_value=Client()), \
                 patch('ai_eda.agent.subagents.tester.test_rtl',side_effect=[baseline,worse,worse]), \
                 patch('ai_eda.agent.subagents.tester.inspect_rtl_structure',return_value={}):
                result=orchestrator.run_agent(project_id='stream_filter',max_repair_attempts=4)
            run=next(Path(tmp).iterdir())
            final=json.loads((run/'result.json').read_text())
            self.assertFalse(final['passed'])
            self.assertEqual(final['tester_attempts'],3)
            self.assertIn('Two consecutive',final['repair_stop_reason'])
            self.assertEqual(final['selected_report'],'tester-01/test_report.json')
            self.assertEqual((run/'project/rtl/core.sv').read_text(),'module core; endmodule\n')
            self.assertTrue((run/'artifacts/rtl_manifest_attempt2.json').exists())
            self.assertTrue((run/'tester-03/test_report.json').exists())
            ev=json.loads((run/'artifacts/repair_evaluation_attempt2.json').read_text())
            self.assertEqual(ev['action'],'rollback')
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)):
                resumed=orchestrator._load_resume_source(run.name)
            self.assertEqual(resumed['project_files']['rtl/core.sv'],'module core; endmodule\n')
            from ai_eda.agent.subagents.base import RunContext
            from ai_eda.agent.subagents.modifier import ModifierAgent
            continuation=RunContext(run_dir=Path(tmp)/'continuation',options={},
                begin_event=lambda *a:None,finish_event=lambda *a,**k:None,persist=lambda *a:None,
                emit=lambda *a:None,check_cancel=lambda:None,request_input=None)
            agent=ModifierAgent(continuation)
            orchestrator._carry_modifier_memory(agent,resumed)
            copied=continuation.read_json_artifact(agent.context['last_repair_evaluation_ref'])
            self.assertEqual(copied['source_run'],run.name)
            self.assertEqual(copied['action'],'rollback')

    def test_rejected_multifile_patch_keeps_only_verified_model_subset(self):
        from ai_eda.agent.subagents.common import safe_project_path
        from ai_eda.agent.subagents.coder import CoderAgent
        from ai_eda.agent.subagents.modifier import ModifierAgent
        class Client:
            def stream_chat_detail(self,messages):
                if 'Spec Parser' in messages[0]['content']:
                    answer={'sufficient':True,'missing':[],'questions':[],'spec_addendum':''}
                else:
                    answer={'top_module':'core','modules':[
                        {'name':'core','file':'rtl/core.sv','interfaces':''},
                        {'name':'helper','file':'rtl/helper.sv','interfaces':''}]}
                yield {'type':'done','answer':json.dumps(answer),'finish_reason':'stop'}
        old={'rtl/core.sv':'module core; endmodule','rtl/helper.sv':'module helper; endmodule'}
        new={'rtl/core.sv':'module core; wire useful; endmodule',
             'rtl/helper.sv':'module helper; wire regresses; endmodule'}
        def publish(runtime,incoming,files,label,source,attempt=None):
            refs=runtime.read_handoff(incoming)['payload']['artifacts']
            for path,text in files.items():
                target=safe_project_path(runtime.run_dir,path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text)
            manifest=runtime.snapshot_rtl_manifest(files,label)
            for e in manifest['files']: e['implementation']='model' if source=='coder' else 'model_repair'
            manifest_ref=runtime.write_json_artifact(label+'.json',manifest)
            return runtime.write_handoff(source,'tester',{'changed_paths':list(files),'artifacts':{
                'spec':refs['spec'],'plan':refs['plan'],'rtl_manifest':manifest_ref}},attempt=attempt)
        def coder(agent,incoming,**kwargs): return publish(agent.runtime,incoming,old,'initial','coder')
        def modifier(agent,incoming,attempt): return publish(agent.runtime,incoming,new,'candidate','modifier',attempt)
        reports=[report(('alu','wrong'),('mem','wrong')),report(('mem','等待 halted 超时')),
                 report(('mem','wrong')),report(('alu','wrong'),('mem','等待 halted 超时'))]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)), \
                 patch('ai_eda.agent.subagents.base.RunContext.make_client',return_value=Client()), \
                 patch.object(CoderAgent,'run',coder),patch.object(ModifierAgent,'run',modifier) as unused, \
                 patch('ai_eda.agent.subagents.tester.test_rtl',side_effect=reports), \
                 patch('ai_eda.agent.subagents.tester.inspect_rtl_structure',return_value={}):
                orchestrator.run_agent(project_id='stream_filter',max_repair_attempts=1)
            run=next(Path(tmp).iterdir()); result=json.loads((run/'result.json').read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['selected_report'],'tester-03/test_report.json')
            self.assertEqual(result['tester_attempts'],4)
            self.assertEqual((run/'project/rtl/core.sv').read_text(),new['rtl/core.sv'])
            self.assertEqual((run/'project/rtl/helper.sv').read_text(),old['rtl/helper.sv'])
            self.assertTrue((run/'artifacts/candidate.json').exists())
            self.assertTrue((run/'artifacts/rtl_manifest_ablation2_1.json').exists())

    def test_invalid_model_patch_stops_with_selected_tested_baseline(self):
        from ai_eda.agent.subagents.modifier import ModifierAgent,InvalidModelRepair
        class Client:
            def stream_chat_detail(self,messages):
                if 'Spec Parser' in messages[0]['content']:
                    answer={'sufficient':True,'missing':[],'questions':[],'spec_addendum':''}
                elif 'RTL Planner' in messages[0]['content']:
                    answer={'top_module':'core','modules':[{'name':'core','file':'rtl/core.sv','interfaces':''}]}
                else:
                    yield {'type':'done','answer':'module core; endmodule','finish_reason':'stop'};return
                yield {'type':'done','answer':json.dumps(answer),'finish_reason':'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',Path(tmp)), \
                 patch('ai_eda.agent.subagents.base.RunContext.make_client',return_value=Client()), \
                 patch('ai_eda.agent.subagents.tester.test_rtl',return_value=report(('case','wrong'))), \
                 patch('ai_eda.agent.subagents.tester.inspect_rtl_structure',return_value={}), \
                 patch.object(ModifierAgent,'run',side_effect=InvalidModelRepair('syntax fixture failed')):
                orchestrator.run_agent(project_id='stream_filter',max_repair_attempts=2)
            run=next(Path(tmp).iterdir());result=json.loads((run/'result.json').read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['selected_report'],'tester-01/test_report.json')
            self.assertIn('syntax fixture failed',result['repair_stop_reason'])
            self.assertEqual((run/'project/rtl/core.sv').read_text(),'module core; endmodule\n')
