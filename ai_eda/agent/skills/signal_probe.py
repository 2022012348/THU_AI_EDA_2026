"""Execute a model-selected, strictly read-only signal observation plan.

The model supplies paths, never executable HDL. The runtime emits a bounded
observer in a separate replay; its early finish is not an acceptance result.
"""
from __future__ import annotations
import re
import subprocess
import tempfile
from pathlib import Path
from ai_eda.rtl.runner import _cpu_feature_compile_flags

PREFIX = 'tb_agent_rv32i5.u_teacher_tb.'
MARKER = 'AI_EDA_SIGNAL_PROBE|'
PATH = re.compile(r'dut(?:\.[A-Za-z_][A-Za-z0-9_$]*)+(?:\[\d{1,4}\])?\Z')


def observer_source(plan: dict, allowed_tests: set[str]) -> str:
    case = plan.get('testcase')
    signals = plan.get('signals')
    trigger = plan.get('trigger')
    if case not in allowed_tests or not isinstance(case, str) or not re.fullmatch(r'[A-Za-z0-9_]+', case):
        raise ValueError('testcase must name an actually failing teacher test')
    if not isinstance(signals, list) or not 1 <= len(signals) <= 10:
        raise ValueError('request 1..10 DUT signal paths')
    if any(not isinstance(s, str) or len(s) > 160 or not PATH.fullmatch(s) for s in signals):
        raise ValueError('only read-only dut.instance.signal paths with optional constant index are supported')
    if trigger is not None and (not isinstance(trigger, str) or not PATH.fullmatch(trigger)):
        raise ValueError('trigger must be a single DUT signal path')
    start = f'({PREFIX}{trigger} === 1\'b1)' if trigger else "1'b1"
    fields = '|'.join(f's{i}=%h' for i in range(len(signals)))
    args = ', '.join(PREFIX + signal for signal in signals)
    return f'''`timescale 1ns/1ps
module agent_signal_probe;
  integer n=0, cycle=0, warmup=0;
  reg started=0;
  always @(posedge {PREFIX}clk) begin
    if ({PREFIX}rst_n && {PREFIX}cur_test == "{case}") begin
      cycle=cycle+1;
      if ({start}) started=1;
      if (!started && warmup < 8) begin
        $display("{MARKER}warmup=1|cycle=%0d|{fields}", cycle, {args});
        warmup=warmup+1;
      end
      if (started && n < 48) begin
        $display("{MARKER}cycle=%0d|{fields}", cycle, {args});
        n=n+1;
        if (n == 48) $finish;
      end
    end
  end
  final $display("{MARKER}summary=1|test_cycles=%0d|trigger_seen=%b|captured=%0d", cycle, started, n);
endmodule
'''


def run_signal_probe(*, project: dict, combined_path: Path, output_dir: Path,
                     plan: dict, allowed_tests: set[str]) -> dict:
    result = {'status': 'not_observed', 'plan': plan, 'samples': [],
              'scope': 'Separate read-only replay, up to 48 consecutive pre-edge samples after optional trigger. Early finish is diagnostic only. No acceptance verdict or proven root cause.'}
    if project.get('testbench_top') != 'tb_agent_rv32i5':
        return dict(result, status='not_covered')
    try:
        source = observer_source(plan, allowed_tests)
    except (ValueError, TypeError) as error:
        return dict(result, status='rejected', detail=str(error))
    result['signal_map']={f's{i}':path for i,path in enumerate(plan['signals'])}
    output_dir.mkdir(parents=True, exist_ok=True)
    probe = output_dir/'observer.sv'; probe.write_text(source, encoding='utf-8')
    teacher = Path(project['testbench_path'])
    with tempfile.TemporaryDirectory(prefix='eda-signal-probe-') as tmp:
        binary = Path(tmp)/'probe.vvp'
        try:
            compile_result = subprocess.run(['iverilog', '-g2012', *_cpu_feature_compile_flags(combined_path),
                '-I', str(teacher.parent), '-s', 'tb_agent_rv32i5', '-s', 'agent_signal_probe',
                '-o', str(binary), str(teacher), str(combined_path), str(probe)],
                capture_output=True, text=True, timeout=15, check=False)
            compile_log = compile_result.stdout + compile_result.stderr
            (output_dir/'compile.log').write_text(compile_log, encoding='utf-8')
            if compile_result.returncode:
                # One misspelled data signal must not discard every valid
                # observation. Drop only compiler-proven missing data paths;
                # never rename signals or silently change the trigger.
                missing = set(re.findall(r"Unable to bind wire/reg/memory `([^']+)'", compile_log))
                bad = [s for s in plan['signals'] if PREFIX+s in missing]
                good = [s for s in plan['signals'] if s not in bad]
                if bad and good and PREFIX+str(plan.get('trigger')) not in missing:
                    (output_dir/'compile_initial.log').write_text(compile_log, encoding='utf-8')
                    effective = dict(plan, signals=good)
                    probe.write_text(observer_source(effective, allowed_tests), encoding='utf-8')
                    result.update(requested_plan=plan, plan=effective, omitted_signals=bad)
                    result['signal_map']={f's{i}':path for i,path in enumerate(good)}
                    compile_result = subprocess.run(compile_result.args, capture_output=True,
                        text=True, timeout=15, check=False)
                    compile_log = compile_result.stdout + compile_result.stderr
                    (output_dir/'compile.log').write_text(compile_log, encoding='utf-8')
            if compile_result.returncode:
                errors = [line for line in compile_log.splitlines() if 'error' in line.lower()]
                return dict(result, status='error', detail='\n'.join(errors[-8:])[-1800:])
            command = ['vvp', str(binary)]
            if project.get('expected_cpu_level') is not None:
                command.append('+expected_cpu_level=' + str(project['expected_cpu_level']))
            simulation = subprocess.run(command, capture_output=True, text=True,
                timeout=min(60, int(project.get('timeout_seconds', 120))), check=False)
            output = simulation.stdout + simulation.stderr
        except subprocess.TimeoutExpired:
            return dict(result, status='timeout', detail='diagnostic replay exceeded wall-clock limit')
        except FileNotFoundError:
            return dict(result, status='unavailable')
    (output_dir/'simulation.log').write_text(output, encoding='utf-8')
    for line in output.splitlines():
        if line.startswith(MARKER):
            fields = dict(item.split('=', 1) for item in line[len(MARKER):].split('|') if '=' in item)
            if fields.pop('summary', None):
                result['capture_summary'] = fields
            elif fields.pop('warmup', None):
                result.setdefault('pretrigger_samples', []).append(fields)
            else:
                result['samples'].append(fields)
    result['samples'] = result['samples'][:48]
    if result['samples']:
        result['status'] = 'observed_partial' if result.get('omitted_signals') else 'observed'
    elif result.get('pretrigger_samples'):
        result['status'] = 'trigger_not_observed'
        result['detail'] = 'Target test was sampled but trigger never became 1; pretrigger samples provided. This does not prove the proposed hypothesis.'
    return result
