import json
import tempfile
import unittest
from pathlib import Path
from ai_eda.agent.subagents.base import RunContext
from ai_eda.agent.subagents.planner import PlannerAgent
from ai_eda.agent.subagents.common import validate_plan

class PlanProtocolReviewTests(unittest.TestCase):
    def test_model_reviews_internal_lifetimes_before_coder_without_changing_top(self):
        calls=[]; events=[]
        draft={'top_module':'rv32i5','modules':[
            {'name':'rv32i5','file':'rtl/rv32i5.sv','interfaces':'input logic clk'},
            {'name':'stage','file':'rtl/stage.sv','interfaces':'input logic clk'}],
            'notes':'draft ownership'}
        review={'issues':['consumer token lifetime unspecified'],
            'timing_contract':'Consumer clears valid after acceptance.',
            'interface_updates':[{'module':'stage','interfaces':'input logic clk, input logic ready'}]}
        class Client:
            def stream_chat_detail(self,messages):
                calls.append(messages)
                answer=review if 'independent CPU protocol contract reviewer' in messages[0]['content'] else draft
                yield {'type':'done','answer':json.dumps(answer),'finish_reason':'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            def begin(node,kind,title,prompt,attempt=1):
                e={'node_id':node,'step':len(events)+1}; events.append(e); return e
            ctx=RunContext(run_dir=Path(tmp),options={'project':{'id':'rv32i5_cache'},'use_l1_reference':False},
                begin_event=begin,finish_event=lambda *a,**k:None,persist=lambda *a:None,
                emit=lambda *a:None,check_cancel=lambda:None,request_input=None)
            ctx.make_client=lambda *a:Client()
            spec=ctx.write_text_artifact('spec.md','Frozen teacher requirements')
            incoming=ctx.write_handoff('parser','planner',{'artifacts':{'spec':spec}})
            out=PlannerAgent(ctx).run(incoming)
            refs=ctx.read_handoff(out)['payload']['artifacts']
            final=ctx.read_json_artifact(refs['plan'])
            self.assertEqual(len(calls),2)
            self.assertEqual(final['notes'],'Consumer clears valid after acceptance.')
            self.assertEqual(final['modules'][0]['interfaces'],draft['modules'][0]['interfaces'])
            self.assertIn('ready',final['modules'][1]['interfaces'])
            self.assertEqual(ctx.read_json_artifact('artifacts/plan_draft.json'),validate_plan(draft))
            self.assertEqual(ctx.read_json_artifact('artifacts/plan_protocol_review.json')['source'],'model')

    def test_failed_protocol_review_resumes_model_draft_without_reparsing(self):
        from unittest.mock import patch
        from ai_eda.agent import orchestrator
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'agent-fixture'; artifacts=run/'artifacts'; artifacts.mkdir(parents=True)
            (artifacts/'effective_spec.md').write_text('frozen spec')
            plan={'top_module':'rv32i5','modules':[{'name':'rv32i5','file':'rtl/rv32i5.sv','interfaces':'input logic clk'}]}
            (artifacts/'plan_draft.json').write_text(json.dumps(plan))
            (run/'events.json').write_text(json.dumps({'status':'failed','project_id':'rv32i5_cache','events':[
                {'node_id':'reviewer','status':'failed','title':'Protocol contract review before Coder'}]}))
            (run/'metadata.json').write_text(json.dumps({'project_id':'rv32i5_cache','use_l1_reference':False}))
            with patch.object(orchestrator,'AGENT_RUNS_ROOT',root):
                source=orchestrator._load_resume_source(run.name)
            self.assertEqual(source['stage'],'contract_review')
            self.assertEqual(source['plan'],plan)
            self.assertEqual(source['project_files'],{})
