"""Read-only replay of the shared teacher harness to expose retire mismatches.

The original acceptance run is untouched. This separate replay stops after five
observations, and its completion is never interpreted as a teacher TB pass.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ai_eda.rtl.runner import _cpu_feature_compile_flags
from ai_eda.agent.skills.pipeline_history import add_pipeline_history, token_presence

MARKER = 'AI_EDA_RETIRE_OBSERVATION|'
OBSERVER = '''`timescale 1ns/1ps
module agent_retirement_observer;
  // PIPELINE_HISTORY_DECL
  integer observed = 0;
  integer sequence_observed = 0;
  integer sequence_cycle = 0, previous_cycle = 0;
  reg previous_valid = 0;
  reg [31:0] previous_pc, previous_insn;
  string previous_test = "";
  // In this no-interrupt RV32I contract, a retired non-control instruction
  // must be followed by pc+4. Branch/JAL/JALR/system instructions are excluded:
  // adjacent equal PCs alone are not evidence of duplicate execution.
  always @(posedge tb_agent_rv32i5.u_teacher_tb.clk) begin
    sequence_cycle = sequence_cycle + 1;
    if (!tb_agent_rv32i5.u_teacher_tb.rst_n ||
        previous_test != tb_agent_rv32i5.u_teacher_tb.cur_test)
    begin
      previous_valid = 0;
      // PIPELINE_HISTORY_RESET
    end
    previous_test = tb_agent_rv32i5.u_teacher_tb.cur_test;
    // PIPELINE_HISTORY_SAMPLE
    if (tb_agent_rv32i5.u_teacher_tb.rst_n && tb_agent_rv32i5.u_teacher_tb.dbg_retire_valid) begin
      case (previous_insn[6:0])
        7'h03,7'h13,7'h17,7'h23,7'h33,7'h37: begin
          if (previous_valid && !$isunknown({previous_pc,tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc}) &&
              tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc !== previous_pc + 32'd4) begin
            // PIPELINE_HISTORY_DUMP
            $display("AI_EDA_RETIRE_OBSERVATION|kind=sequence|test=%s|previous_pc=%h|previous_insn=%h|expected_pc=%h|expected_next_insn=%h|pc=%h|insn=%h|gap_cycles=%0d",
              previous_test,previous_pc,previous_insn,previous_pc+32'd4,
              tb_agent_rv32i5.u_teacher_tb.imem[((previous_pc+32'd4)>>2)&32'h3ff],
              tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc,tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn,
              sequence_cycle-previous_cycle);
            sequence_observed = sequence_observed + 1;
            if (sequence_observed >= 5) $finish;
          end
        end
      endcase
      previous_valid=1;
      previous_pc=tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc;
      previous_insn=tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn;
      previous_cycle=sequence_cycle;
    end
  end
  // Fetch-side history: sampled every cycle so a retire mismatch can be reported
  // together with the instruction-bus traffic that produced it.
  reg [31:0] if_addr0, if_addr1;
  reg [31:0] if_data0, if_data1;
  reg [1:0]  if_vr0;
  reg [31:0] rt_pc0, rt_pc1;
  reg [31:0] rt_in0, rt_in1;
  always @(posedge tb_agent_rv32i5.u_teacher_tb.clk) begin
    if_addr1 <= if_addr0;
    if_addr0 <= tb_agent_rv32i5.u_teacher_tb.imem_addr;
    if_data1 <= if_data0;
    if_data0 <= tb_agent_rv32i5.u_teacher_tb.imem_rdata;
    if_vr0 <= {tb_agent_rv32i5.u_teacher_tb.imem_valid, tb_agent_rv32i5.u_teacher_tb.imem_ready};
    if (tb_agent_rv32i5.u_teacher_tb.dbg_retire_valid) begin
      rt_pc1 <= rt_pc0; rt_pc0 <= tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc;
      rt_in1 <= rt_in0; rt_in0 <= tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn;
    end
  end
  always @(posedge tb_agent_rv32i5.u_teacher_tb.clk) begin
    if (tb_agent_rv32i5.u_teacher_tb.rst_n && tb_agent_rv32i5.u_teacher_tb.dbg_retire_valid) begin
      if (tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc[1:0] !== 0 ||
          tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn !==
          tb_agent_rv32i5.u_teacher_tb.imem[tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc[11:2]]) begin
        $display("AI_EDA_RETIRE_OBSERVATION|test=%s|pc=%h|insn=%h|expected_insn=%h|imem_addr=%h|imem_valid=%b|imem_ready=%b|imem_rdata=%h|expected_at_addr=%h|insn_at_pc_minus4=%h|pc_minus4=%h|prev_retire=%h:%h|prev_if=%h:%h",
          tb_agent_rv32i5.u_teacher_tb.cur_test,
          tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc,
          tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn,
          tb_agent_rv32i5.u_teacher_tb.imem[tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc[11:2]],
          tb_agent_rv32i5.u_teacher_tb.imem_addr,
          tb_agent_rv32i5.u_teacher_tb.imem_valid,
          tb_agent_rv32i5.u_teacher_tb.imem_ready,
          tb_agent_rv32i5.u_teacher_tb.imem_rdata,
          tb_agent_rv32i5.u_teacher_tb.imem[tb_agent_rv32i5.u_teacher_tb.imem_addr[11:2]],
          (tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc[11:2] == 0) ? 32'h0 :
            tb_agent_rv32i5.u_teacher_tb.imem[tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc[11:2] - 1],
          tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc - 32'd4,
          rt_pc1, rt_in1,
          if_addr1, if_data1);
        observed = observed + 1;
        if (observed >= 5) $finish;
      end
    end
  end
  initial begin #200000; $finish; end
endmodule
'''


def observe_retirement(*, project: dict, combined_path: Path, output_dir: Path) -> dict:
    if project.get('testbench_top') != 'tb_agent_rv32i5':
        return {'status': 'not_covered', 'observations': [], 'detail': 'shared teacher hierarchy not recognized'}
    output_dir.mkdir(parents=True, exist_ok=True)
    observer = output_dir / 'observer.sv'
    observer_source,stages=add_pipeline_history(OBSERVER,combined_path.read_text(encoding='utf-8'))
    observer.write_text(observer_source, encoding='utf-8')
    teacher = Path(project['testbench_path'])
    result = {'status': 'not_observed', 'observations': [], 'sequence_observations': [], 'pipeline_history': [],
              'scope': 'Separate read-only replay: at most five PC/word mismatches or fallthrough sequence violations. For retired load/store/ALU/LUI/AUIPC in this no-interrupt ISA, the next retired PC must be previous PC+4. Control/system predecessors are excluded. Not an acceptance test or proof of a specific IF/WB root cause.'}
    with tempfile.TemporaryDirectory(prefix='eda-retirement-observer-') as tmp:
        binary = Path(tmp) / 'observer.vvp'
        command = ['iverilog', '-g2012', *_cpu_feature_compile_flags(combined_path), '-I', str(teacher.parent),
                   '-s', 'tb_agent_rv32i5', '-s', 'agent_retirement_observer', '-o', str(binary),
                   str(teacher), str(combined_path), str(observer)]
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            (output_dir / 'compile.log').write_text(compiled.stdout + compiled.stderr, encoding='utf-8')
            if compiled.returncode:
                return dict(result, status='error', detail='observer did not compile; no runtime conclusion')
            replay = ['vvp', str(binary)]
            if project.get('expected_cpu_level') is not None:
                replay.append('+expected_cpu_level=' + str(project['expected_cpu_level']))
            simulated = subprocess.run(replay, capture_output=True, text=True, timeout=5, check=False)
            output = simulated.stdout + simulated.stderr
        except subprocess.TimeoutExpired:
            return dict(result, status='timeout', detail='diagnostic replay timed out; no runtime conclusion')
        except FileNotFoundError:
            return dict(result, status='unavailable', detail='Icarus tools unavailable')
    (output_dir / 'simulation.log').write_text(output, encoding='utf-8')
    for line in output.splitlines():
        if line.startswith(MARKER):
            fields = {}
            for item in line[len(MARKER):].split('|'):
                key, separator, value = item.partition('=')
                if separator:
                    fields[key] = value.strip()[:160]
            destination = 'sequence_observations' if fields.pop('kind',None) == 'sequence' else 'observations'
            if 'cycle' in fields and 'retire_pc' in fields:
                if len(result['pipeline_history'])<32:result['pipeline_history'].append(fields)
                continue
            if destination == 'sequence_observations':
                try:
                    opcode=int(fields.get('expected_next_insn',''),16)&0x7f
                except ValueError:
                    opcode=None
                fields['expected_next_kind']={0x03:'load',0x13:'immediate_alu',0x17:'auipc',
                    0x23:'store',0x33:'register_alu',0x37:'lui',0x63:'branch',0x67:'jalr',
                    0x6f:'jal',0x73:'system'}.get(opcode,'unknown')
            if len(result[destination]) < 5:
                result[destination].append(fields)
    if result['observations'] or result['sequence_observations']:
        result['status'] = 'observed'
    if result['pipeline_history'] and result['sequence_observations']:
        result['pipeline_token_presence']=token_presence(result['pipeline_history'],stages,
            result['sequence_observations'][0]['expected_pc'])
    return result
