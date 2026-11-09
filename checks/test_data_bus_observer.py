import shutil
import tempfile
import unittest
from pathlib import Path
from ai_eda.agent.skills.data_bus_observer import observe_data_bus
from ai_eda.agent.subagents.common import report_feedback

@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus required')
class DataBusObserverTests(unittest.TestCase):
    def test_counts_handshakes_separately_per_test_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            teacher=root/'teacher.sv'; rtl=root/'rtl.sv'
            source='''`timescale 1ns/1ps
module fixture;
reg clk=0; always #5 clk=~clk;
reg rst_n=1, dmem_valid=1, dmem_ready=0, dmem_we=1;
reg [31:0] dmem_addr=32'h100, dmem_wdata=32'h1234, dmem_rdata=0;
reg [3:0] dmem_be=15;
reg dbg_retire_valid=1;
reg [31:0] dbg_retire_insn=32'h23, dbg_retire_pc=0;
string cur_test="store_case";
initial begin #10; dmem_ready=1; #10; cur_test="load_case"; dmem_we=0; dbg_retire_insn=32'h03; #10; $finish; end
endmodule
module tb_agent_rv32i5; fixture u_teacher_tb(); endmodule
'''
            teacher.write_text(source); rtl.write_text('module core; endmodule')
            r=observe_data_bus(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},combined_path=rtl,output_dir=root/'out')
            self.assertEqual(r['status'],'observed',r)
            rows={row['test']:row for row in r['tests']}
            self.assertEqual(rows['store_case']['summary']['writes'],'1')
            self.assertEqual(rows['store_case']['summary']['waiting_cycles'],'1')
            self.assertEqual(rows['store_case']['summary']['retired_stores'],'2')
            self.assertEqual(rows['load_case']['summary']['reads'],'1')
            self.assertNotIn('passed',r)
            self.assertEqual(teacher.read_text(),source)
            self.assertEqual(rtl.read_text(),'module core; endmodule')
            f=report_feedback({'passed':False,'checks':[{'name':'store_case','detail':'bad'}],'data_bus_observation':r})
            self.assertIn('1234',f)
            self.assertNotIn('"test": "load_case"',f)
