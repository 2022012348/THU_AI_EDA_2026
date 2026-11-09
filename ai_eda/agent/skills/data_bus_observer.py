"""Bounded, read-only per-test external data-bus evidence; never an acceptance verdict."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from ai_eda.rtl.runner import _cpu_feature_compile_flags

MARKER = 'AI_EDA_DATA_BUS|'
OBSERVER = '''`timescale 1ns/1ps
module agent_data_bus_observer;
  `define T tb_agent_rv32i5.u_teacher_tb
  string active_test = "";
  integer reads=0, writes=0, waiting=0, retired_loads=0, retired_stores=0;
  integer samples=0, cycles=0, retired=0, adjacent_same=0;
  reg previous_valid=0;
  reg [31:0] previous_pc, previous_insn;
  task summary;
    if (active_test != "")
      $display("AI_EDA_DATA_BUS|kind=summary|test=%s|reads=%0d|writes=%0d|waiting_cycles=%0d|retired_loads=%0d|retired_stores=%0d|retired=%0d|adjacent_same=%0d", active_test, reads, writes, waiting, retired_loads, retired_stores, retired, adjacent_same);
  endtask
  always @(posedge `T.clk) begin
    if (active_test != `T.cur_test) begin
      summary(); active_test = `T.cur_test;
      reads=0; writes=0; waiting=0; retired_loads=0; retired_stores=0;
      samples=0; cycles=0; retired=0; adjacent_same=0; previous_valid=0;
    end
    if (!`T.rst_n) previous_valid=0;
    else begin
      cycles=cycles+1;
      if (`T.dmem_valid && !`T.dmem_ready) waiting=waiting+1;
      if (`T.dmem_valid && `T.dmem_ready) begin
        if (`T.dmem_we) writes=writes+1; else reads=reads+1;
        if (samples < 12) begin
          $display("AI_EDA_DATA_BUS|kind=transaction|test=%s|cycle=%0d|we=%b|addr=%h|wdata=%h|be=%b|rdata=%h", active_test, cycles, `T.dmem_we, `T.dmem_addr, `T.dmem_wdata, `T.dmem_be, `T.dmem_rdata);
          samples=samples+1;
        end
      end
      if (`T.dbg_retire_valid) begin
        retired=retired+1;
        if (`T.dbg_retire_insn[6:0] == 7'h03) retired_loads=retired_loads+1;
        if (`T.dbg_retire_insn[6:0] == 7'h23) retired_stores=retired_stores+1;
        if (previous_valid && previous_pc == `T.dbg_retire_pc && previous_insn == `T.dbg_retire_insn) adjacent_same=adjacent_same+1;
        previous_valid=1; previous_pc=`T.dbg_retire_pc; previous_insn=`T.dbg_retire_insn;
      end
    end
  end
  final begin
    if (active_test != "")
      $display("AI_EDA_DATA_BUS|kind=summary|test=%s|reads=%0d|writes=%0d|waiting_cycles=%0d|retired_loads=%0d|retired_stores=%0d|retired=%0d|adjacent_same=%0d", active_test, reads, writes, waiting, retired_loads, retired_stores, retired, adjacent_same);
  end
  `undef T
endmodule
'''


def observe_data_bus(*, project: dict, combined_path: Path, output_dir: Path) -> dict:
    result = {'status': 'not_observed', 'tests': [], 'scope':
              'Separate read-only replay. Counts external valid && ready handshakes and retired opcodes per teacher test; first 12 transactions per test. Cache hits need no external read. Adjacent identical retirements can be legal loops, not proof of duplicate execution. No acceptance verdict.'}
    if project.get('testbench_top') != 'tb_agent_rv32i5':
        return dict(result, status='not_covered')
    output_dir.mkdir(parents=True, exist_ok=True)
    observer = output_dir / 'observer.sv'
    observer.write_text(OBSERVER, encoding='utf-8')
    teacher = Path(project['testbench_path'])
    with tempfile.TemporaryDirectory(prefix='eda-data-bus-') as tmp:
        binary = Path(tmp) / 'observer.vvp'
        try:
            compiled = subprocess.run(['iverilog', '-g2012', *_cpu_feature_compile_flags(combined_path),
                '-I', str(teacher.parent), '-s', 'tb_agent_rv32i5', '-s', 'agent_data_bus_observer',
                '-o', str(binary), str(teacher), str(combined_path), str(observer)],
                capture_output=True, text=True, timeout=15, check=False)
            (output_dir / 'compile.log').write_text(compiled.stdout + compiled.stderr, encoding='utf-8')
            if compiled.returncode:
                return dict(result, status='error', detail='observer compilation failed')
            command = ['vvp', str(binary)]
            if project.get('expected_cpu_level') is not None:
                command.append('+expected_cpu_level=' + str(project['expected_cpu_level']))
            simulated = subprocess.run(command, capture_output=True, text=True,
                timeout=int(project.get('timeout_seconds', 120)), check=False)
            output = simulated.stdout + simulated.stderr
        except subprocess.TimeoutExpired:
            return dict(result, status='timeout', detail='replay incomplete; no conclusion')
        except FileNotFoundError:
            return dict(result, status='unavailable')
    (output_dir / 'simulation.log').write_text(output, encoding='utf-8')
    tests = {}
    for line in output.splitlines():
        if not line.startswith(MARKER):
            continue
        fields = dict(item.split('=', 1) for item in line[len(MARKER):].split('|') if '=' in item)
        name = fields.pop('test', '').strip()
        if name not in tests and len(tests) >= 64:
            continue
        row = tests.setdefault(name, {'test': name, 'transactions': []})
        if fields.pop('kind', '') == 'summary':
            row['summary'] = fields
        elif len(row['transactions']) < 12:
            row['transactions'].append(fields)
    result['tests'] = list(tests.values())
    if tests:
        result['status'] = 'observed'
    return result
