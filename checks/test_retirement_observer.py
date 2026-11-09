import shutil
import tempfile
import unittest
from pathlib import Path

from ai_eda.agent.skills.retirement_observer import observe_retirement


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus required')
class RetirementObserverTests(unittest.TestCase):
    def test_observer_records_actual_and_expected_without_rewriting_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, rtl = root / 'teacher.sv', root / 'generated.sv'
            source = '''`timescale 1ns/1ps
module teacher_fixture;
reg clk=0; always #5 clk=~clk;
reg rst_n=1;
reg dbg_retire_valid=1;
reg [31:0] dbg_retire_pc=0, dbg_retire_insn=32'h00000013;
reg [31:0] imem[0:1023];
reg [31:0] imem_addr=0;
reg imem_valid=1, imem_ready=1;
wire [31:0] imem_rdata = imem[imem_addr[11:2]];
string cur_test="case";
initial imem[0]=32'h00100093;
endmodule
module tb_agent_rv32i5; teacher_fixture u_teacher_tb(); endmodule
'''
            teacher.write_text(source)
            rtl.write_text('module core; endmodule')
            result = observe_retirement(project={'testbench_top': 'tb_agent_rv32i5', 'testbench_path': teacher},
                                        combined_path=rtl, output_dir=root / 'diagnostic')
            self.assertEqual(result['status'], 'observed', result)
            self.assertEqual(len(result['observations']), 5)
            self.assertEqual(result['observations'][0]['expected_insn'], '00100093')
            self.assertEqual(result['observations'][0]['insn'], '00000013')
            self.assertNotIn('passed', result)
            self.assertEqual(teacher.read_text(), source)
            self.assertEqual(rtl.read_text(), 'module core; endmodule')

    def test_legal_self_jump_is_excluded_but_repeated_linear_retirement_is_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); teacher=root/'teacher.sv'; rtl=root/'rtl.sv'
            source='''`timescale 1ns/1ps
module teacher_fixture;
reg clk=0; always #5 clk=~clk;
reg rst_n=1, dbg_retire_valid=1;
reg [31:0] dbg_retire_pc=0,dbg_retire_insn=32'h0000006f;
reg [31:0] imem[0:1023];
reg [31:0] imem_addr=0;
reg imem_valid=1,imem_ready=1;
wire [31:0] imem_rdata=imem[0];
string cur_test="case";
initial begin imem[0]=32'h0000006f; imem[1]=32'h0010a023; #70; imem[0]=32'h00000013; dbg_retire_insn=32'h00000013; #1000; $finish; end
endmodule
module tb_agent_rv32i5; teacher_fixture u_teacher_tb(); endmodule
'''
            teacher.write_text(source); rtl.write_text('module core; endmodule')
            result=observe_retirement(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'out')
            self.assertEqual(result['status'],'observed',result)
            self.assertEqual(result['observations'],[])
            self.assertEqual(len(result['sequence_observations']),5)
            for row in result['sequence_observations']:
                self.assertEqual(row['previous_insn'],'00000013')
                self.assertEqual(row['expected_pc'],'00000004')
                self.assertEqual(row['pc'],'00000000')
                self.assertEqual(row['expected_next_insn'],'0010a023')
                self.assertEqual(row['expected_next_kind'],'store')
            self.assertEqual(teacher.read_text(),source)

    def test_ordinary_sequential_retirement_has_no_sequence_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); teacher=root/'teacher.sv'; rtl=root/'rtl.sv'
            teacher.write_text('''`timescale 1ns/1ps
module teacher_fixture;
reg clk=0; always #5 clk=~clk;
reg rst_n=1,dbg_retire_valid=1;
reg [31:0] dbg_retire_pc=0,dbg_retire_insn=32'h00000013;
reg [31:0] imem[0:1023];
reg [31:0] imem_addr=0;
reg imem_valid=1,imem_ready=1;
wire [31:0] imem_rdata=imem[0];
string cur_test="case";
integer i;
initial begin for(i=0;i<1024;i=i+1) imem[i]=32'h00000013; #1000; $finish; end
always @(posedge clk) dbg_retire_pc<=dbg_retire_pc+4;
endmodule
module tb_agent_rv32i5; teacher_fixture u_teacher_tb(); endmodule
''')
            rtl.write_text('module core; endmodule')
            result=observe_retirement(project={'testbench_top':'tb_agent_rv32i5','testbench_path':teacher},
                combined_path=rtl,output_dir=root/'out')
            self.assertEqual(result['status'],'not_observed',result)
            self.assertEqual(result['sequence_observations'],[])
