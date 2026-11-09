import unittest
from ai_eda.agent.skills.pipeline_history import add_pipeline_history,token_presence

class PipelineHistoryTests(unittest.TestCase):
    def test_recognized_declared_nets_only_and_read_only_source(self):
        rtl='''module rv32i5;
logic [31:0] if_id_pc,id_ex_pc;
logic if_id_valid,id_ex_valid;
logic [15:0] ex_mem_pc;
logic ex_mem_valid;
logic mem_stall;
endmodule'''
        template='// PIPELINE_HISTORY_DECL\n// PIPELINE_HISTORY_RESET\n// PIPELINE_HISTORY_SAMPLE\n// PIPELINE_HISTORY_DUMP'
        source,stages=add_pipeline_history(template,rtl)
        self.assertEqual(stages,['if_id','id_ex'])
        self.assertIn('tb_agent_rv32i5.u_teacher_tb.dut.if_id_pc',source)
        self.assertIn('kind=stage_history',source)
        self.assertNotIn('dut.ex_mem_pc',source)
        self.assertNotIn('force ',source)
        self.assertNotIn('PIPELINE_HISTORY_',source)
        source,stages=add_pipeline_history(template,'module other; endmodule')
        self.assertEqual(source,template);self.assertEqual(stages,[])

    def test_presence_requires_valid_and_preserves_window_scope(self):
        rows=[{'cycle':'10','if_id_pc':'00000008','if_id_valid':'1','ex_mem_pc':'00000008','ex_mem_valid':'0'},
              {'cycle':'11','if_id_pc':'00000008','if_id_valid':'1','ex_mem_pc':'00000008','ex_mem_valid':'1'}]
        result=token_presence(rows,['if_id','ex_mem'],'00000008')
        self.assertEqual(result['stages'][0]['valid_samples'],2)
        self.assertEqual(result['stages'][1]['valid_samples'],1)
        self.assertEqual(result['stages'][1]['first_cycle'],'11')
        self.assertIn('unproven',result['scope'])
