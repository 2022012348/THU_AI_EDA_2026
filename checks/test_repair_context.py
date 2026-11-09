import copy
import unittest
from ai_eda.agent.repair_context import select_repair_context,requested_context

class RepairContextTests(unittest.TestCase):
    def test_selects_actual_producer_consumer_and_top_without_mutating_snapshot(self):
        files={'rtl/top.sv':'module rv32i5; endmodule',
            'rtl/ex.sv':'module ex_stage(output logic [31:0] ex_mem_pc); endmodule',
            'rtl/mem.sv':'module mem_stage(input logic [31:0] ex_mem_pc, output logic [31:0] mem_wb_pc); endmodule',
            'rtl/cache.sv':'module cache; endmodule'}
        plan={'top_module':'rv32i5','modules':[{'name':n,'file':p} for n,p in
            [('rv32i5','rtl/top.sv'),('ex_stage','rtl/ex.sv'),('mem_stage','rtl/mem.sv'),('cache','rtl/cache.sv')]]}
        ticket={'pipeline_token_presence':{'stages':[{'stage':'ex_mem','valid_samples':2},
            {'stage':'mem_wb','valid_samples':0},{'stage':'retire','valid_samples':0}]}}
        old=copy.deepcopy(files)
        selected=select_repair_context(files,plan,ticket)
        self.assertEqual(set(selected),{'rtl/top.sv','rtl/ex.sv','rtl/mem.sv'})
        self.assertEqual(files,old)
        self.assertEqual(requested_context(files,selected,['rtl/cache.sv']),{'rtl/cache.sv':files['rtl/cache.sv']})
        with self.assertRaises(ValueError):requested_context(files,selected,['.api_key'])
        with self.assertRaises(ValueError):requested_context(files,selected,['rtl/top.sv'])
        self.assertEqual(select_repair_context(files,plan,None),files)

    def test_modifier_can_request_omitted_source_then_patch_full_snapshot(self):
        import json,tempfile
        from pathlib import Path
        from ai_eda.agent.subagents.base import RunContext
        from ai_eda.agent.subagents.modifier import ModifierAgent
        from ai_eda.agent.repair_focus import make_repair_ticket
        files={'rtl/top.sv':'module rv32i5; endmodule',
            'rtl/ex.sv':'module ex_stage(output logic [31:0] ex_mem_pc); endmodule',
            'rtl/mem.sv':'module mem_stage(input logic [31:0] ex_mem_pc, output logic [31:0] mem_wb_pc); endmodule',
            'rtl/cache.sv':'module cache; wire old_signal; endmodule'}
        plan={'top_module':'rv32i5','modules':[{'name':n,'file':p,'interfaces':''} for n,p in
            [('rv32i5','rtl/top.sv'),('ex_stage','rtl/ex.sv'),('mem_stage','rtl/mem.sv'),('cache','rtl/cache.sv')]]}
        report={'passed':False,'stage':'simulation','checks':[{'name':'case','detail':'wrong'}],
            'retirement_observation':{'observations':[], 'sequence_observations':[
                {'test':'case','previous_pc':'00000004','previous_insn':'00408093','expected_pc':'00000008','pc':'00000004'}],
                'pipeline_history':[{'test':'case','cycle':'10','ex_mem_pc':'00000008'}],
                'pipeline_token_presence':{'target_pc':'00000008','stages':[
                    {'stage':'ex_mem','valid_samples':2},{'stage':'mem_wb','valid_samples':0},{'stage':'retire','valid_samples':0}]}}}
        ticket=make_repair_ticket(report);calls=[];events=[]
        class Client:
            def stream_chat_detail(self,messages):
                calls.append(messages)
                payload={'ticket_id':ticket['id']}
                if len(calls)==1:payload['request_context']=['rtl/cache.sv']
                else:payload.update(edits=[{'path':'rtl/cache.sv','before':'wire old_signal;','after':'wire new_signal;'}],notes='model repair')
                yield {'type':'done','answer':json.dumps(payload),'finish_reason':'stop'}
        with tempfile.TemporaryDirectory() as tmp:
            def begin(node,kind,title,prompt,attempt=1):
                e={'step':len(events)+1,'node_id':node};events.append(e);return e
            ctx=RunContext(run_dir=Path(tmp),options={'project':{'id':'rv32i5_cache'}},begin_event=begin,
                finish_event=lambda *a,**k:None,persist=lambda *a:None,emit=lambda *a:None,
                check_cancel=lambda:None,request_input=None)
            ctx.make_client=lambda *a:Client()
            spec=ctx.write_text_artifact('spec.md','frozen spec')
            plan_ref=ctx.write_json_artifact('plan.json',plan)
            manifest=ctx.snapshot_rtl_manifest(files,'baseline')
            for e in manifest['files']:e['implementation']='model'
            manifest_ref=ctx.write_json_artifact('manifest.json',manifest)
            report_ref=ctx.write_json_artifact('report.json',report)
            incoming=ctx.write_handoff('tester','modifier',{'artifacts':{
                'spec':spec,'plan':plan_ref,'rtl_manifest':manifest_ref,'report':report_ref}})
            out=ModifierAgent(ctx).run(incoming,1)
            result=ctx.read_json_artifact(ctx.read_handoff(out)['payload']['artifacts']['rtl_manifest'])
            self.assertEqual(len(calls),2)
            self.assertIn('module cache; wire old_signal;',calls[1][-1]['content'])
            self.assertEqual(len(result['files']),4)
            self.assertTrue((Path(tmp)/'artifacts/context_answer_attempt1.json').exists())
            self.assertEqual((Path(tmp)/'project/rtl/cache.sv').read_text(),'module cache; wire new_signal; endmodule')
