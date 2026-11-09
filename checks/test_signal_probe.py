import shutil
import tempfile
import unittest
from pathlib import Path
from ai_eda.agent.skills.signal_probe import observer_source, run_signal_probe

class ProbeValidationTests(unittest.TestCase):
    def test_model_cannot_supply_hdl_or_other_testbench_state(self):
        for signal in ('dut.x); $finish; //', 'imem[0]', 'dut.a + dut.b', 'dut.a[1:0]', 'dut.x; force dut.y=1;'):
            with self.assertRaises(ValueError):
                observer_source({'testcase':'case','signals':[signal]}, {'case'})
        with self.assertRaises(ValueError):
            observer_source({'testcase':'other','signals':['dut.x']}, {'case'})

@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus required')
class SignalProbeTests(unittest.TestCase):
    def test_actual_samples_trigger_limit_and_unchanged_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); teacher=root/'teacher.sv'; rtl=root/'rtl.sv'
            source='''`timescale 1ns/1ps
module core(input clk);
reg [31:0] count=0;
wire active=count>=3;
wire never=0;
always @(posedge clk) count<=count+1;
endmodule
module fixture;
reg clk=0; always #5 clk=~clk;
reg rst_n=1;
string cur_test="case";
core dut(clk);
initial begin #10000; $finish; end
endmodule
module tb_agent_rv32i5; fixture u_teacher_tb(); endmodule
'''
            teacher.write_text(source); rtl.write_text('module dummy; endmodule')
            plan={'testcase':'case','signals':['dut.count','dut.active'],'trigger':'dut.active'}
            r=run_signal_probe(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'out',plan=plan,allowed_tests={'case'})
            self.assertEqual(r['status'],'observed',r)
            self.assertEqual(len(r['samples']),48)
            self.assertEqual(r['samples'][0]['s0'],'00000003')
            self.assertEqual(r['samples'][-1]['s0'],'00000032')
            self.assertNotIn('passed',r)
            self.assertEqual(teacher.read_text(),source)
            self.assertEqual(rtl.read_text(),'module dummy; endmodule')
            missing=run_signal_probe(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'missing',
                plan={'testcase':'case','signals':['dut.count'],'trigger':'dut.missing'},allowed_tests={'case'})
            self.assertEqual(missing['status'],'error')
            partial=run_signal_probe(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'partial',
                plan={'testcase':'case','signals':['dut.count','dut.missing'],'trigger':'dut.active'},allowed_tests={'case'})
            self.assertEqual(partial['status'],'observed_partial',partial)
            self.assertEqual(partial['omitted_signals'],['dut.missing'])
            self.assertEqual(partial['plan']['signals'],['dut.count'])
            self.assertEqual(partial['samples'][0]['s0'],'00000003')
            untriggered=run_signal_probe(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'untriggered',
                plan={'testcase':'case','signals':['dut.count'],'trigger':'dut.never'},allowed_tests={'case'})
            self.assertEqual(untriggered['status'],'trigger_not_observed')
            self.assertEqual(len(untriggered['pretrigger_samples']),8)
            self.assertEqual(untriggered['capture_summary']['trigger_seen'],'0')

class ModifierDialogueTests(unittest.TestCase):
    def test_modifier_can_ask_tester_before_emitting_a_patch(self):
        import json
        from unittest.mock import patch
        from ai_eda.agent.subagents.base import RunContext
        from ai_eda.agent.subagents.modifier import ModifierAgent
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); calls=[]; events=[]; model_options=[]
            def begin(node,kind,title,prompt,attempt=1):
                e={'step':len(events)+1,'node_id':node}; events.append(e); return e
            ctx=RunContext(run_dir=root,options={'project':{'id':'rv32i5_cache'}},begin_event=begin,
                finish_event=lambda *a,**k:None,persist=lambda *a:None,emit=lambda *a:None,
                check_cancel=lambda:None,request_input=None)
            class Client:
                def stream_chat_detail(self,messages):
                    calls.append(messages)
                    if len(calls)==1:
                        answer={'hypothesis':'test dependency','request_observation':{'testcase':'case','signals':['dut.valid']}}
                    else:
                        answer={'edits':[{'path':'rtl/core.sv','before':'wire old_signal;',
                                          'after':'wire broken = ;' if len(calls)==2 else 'wire new_signal;'}],'notes':'model repair'}
                    yield {'type':'done','answer':json.dumps(answer),'finish_reason':'stop'}
            def make(overrides=None):model_options.append(overrides);return Client()
            ctx.make_client=make
            files={'rtl/core.sv':'module core; wire old_signal; endmodule'}
            spec=ctx.write_text_artifact('spec.md','frozen spec')
            plan=ctx.write_json_artifact('plan.json',{'top_module':'core','modules':[
                {'name':'core','file':'rtl/core.sv','interfaces':''}]})
            manifest=ctx.write_json_artifact('manifest.json',ctx.snapshot_rtl_manifest(files,'baseline'))
            report=ctx.write_json_artifact('report.json',{'passed':False,'stage':'simulation','checks':[{'name':'case','detail':'wrong'}]})
            incoming=ctx.write_handoff('tester','modifier',{'artifacts':{'spec':spec,'plan':plan,'rtl_manifest':manifest,'report':report}})
            with patch('ai_eda.agent.subagents.tester.run_signal_probe',return_value={
                'status':'observed','samples':[{'cycle':'1','s0':'1'}]}) as observer, \
                 patch('ai_eda.agent.subagents.modifier._syntax_error',side_effect=['fixture syntax error',None]):
                ModifierAgent(ctx).run(incoming,1)
            self.assertEqual(len(calls),3)
            self.assertFalse(model_options[0]['thinking'])
            self.assertTrue(model_options[1]['thinking'])
            self.assertEqual(model_options[1]['reasoning_effort'],'low')
            self.assertEqual(model_options[1]['max_tokens'],16000)
            self.assertIn('"status": "observed"',calls[1][-1]['content'])
            self.assertIn('同一个功能假设',calls[2][-1]['content'])
            self.assertEqual(observer.call_count,1)
            self.assertTrue((root/'artifacts/observation_request_attempt1.json').exists())
            self.assertTrue((root/'artifacts/observation_answer_attempt1.json').exists())
            contract=json.loads((root/'artifacts/repair_contract_attempt1.json').read_text())
            self.assertTrue(contract['observation_requested'])
            self.assertIn('new_signal',(root/'project/rtl/core.sv').read_text())

    def test_automatic_pipeline_history_avoids_an_extra_observation_call(self):
        import json
        from unittest.mock import patch
        from ai_eda.agent.subagents.base import RunContext
        from ai_eda.agent.subagents.modifier import ModifierAgent
        from ai_eda.agent.repair_focus import make_repair_ticket
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);events=[];options=[]
            def begin(node,kind,title,prompt,attempt=1):
                e={'step':len(events)+1,'node_id':node};events.append(e);return e
            ctx=RunContext(run_dir=root,options={'project':{'id':'rv32i5_cache'}},begin_event=begin,
                finish_event=lambda *a,**k:None,persist=lambda *a:None,emit=lambda *a:None,
                check_cancel=lambda:None,request_input=None)
            report={'passed':False,'stage':'simulation','checks':[{'name':'case','detail':'wrong'}],
                'retirement_observation':{'observations':[], 'sequence_observations':[
                    {'test':'case','previous_pc':'00000004','previous_insn':'00408093','expected_pc':'00000008','pc':'00000004'}],
                    'pipeline_history':[{'test':'case','cycle':'10','ex_mem_pc':'00000008'}],
                    'pipeline_token_presence':{'target_pc':'00000008','stages':[]}}}
            ticket=make_repair_ticket(report)
            class Client:
                def stream_chat_detail(self,messages):
                    yield {'type':'done','answer':json.dumps({'ticket_id':ticket['id'],'edits':[
                        {'path':'rtl/core.sv','before':'wire old_signal;','after':'wire new_signal;'}],'notes':'repair'}),
                        'finish_reason':'stop'}
            def make(overrides=None):options.append(overrides);return Client()
            ctx.make_client=make
            spec=ctx.write_text_artifact('spec.md','frozen spec')
            plan=ctx.write_json_artifact('plan.json',{'top_module':'rv32i5','modules':[
                {'name':'rv32i5','file':'rtl/core.sv','interfaces':''}]})
            manifest=ctx.write_json_artifact('manifest.json',ctx.snapshot_rtl_manifest(
                {'rtl/core.sv':'module rv32i5; wire old_signal; endmodule'},'baseline'))
            report_ref=ctx.write_json_artifact('report.json',report)
            incoming=ctx.write_handoff('tester','modifier',{'artifacts':{
                'spec':spec,'plan':plan,'rtl_manifest':manifest,'report':report_ref}})
            agent=ModifierAgent(ctx);agent.save_context(failing_tests=['case'])
            with patch('ai_eda.agent.subagents.tester.run_signal_probe',side_effect=AssertionError('redundant probe')):
                agent.run(incoming,1)
            self.assertEqual(ctx.model_calls,1)
            self.assertTrue(options[0]['thinking'])
            self.assertEqual(options[0]['max_tokens'],16000)
            self.assertFalse((root/'artifacts/independent_review_attempt1.json').exists())
