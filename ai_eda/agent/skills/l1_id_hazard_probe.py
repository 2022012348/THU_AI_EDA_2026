"""Directed check for one explicitly recognized L1 ID/hazard topology.

This is an additive probe, not the teacher TB. Other implementation
architectures are reported as not covered rather than presumed incorrect.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ai_eda.agent.rtl_contracts import _group, _split_ports, extract_module_header
from ai_eda.config import AGENT_CONTENT_ROOT

PROBE_TB = AGENT_CONTENT_ROOT / 'verification' / 'l1_id_hazard_tb.sv'
PROBE_NAME = 'l1_id_hazard'
PASS_MARKER = 'L1_ID_HAZARD_PASS'

ID_REQUIRED = {
    'clk': ('input', 1), 'rst_n': ('input', 1),
    'if_id_valid': ('input', 1), 'if_id_pc': ('input', 32), 'if_id_insn': ('input', 32),
    'id_stall': ('input', 1), 'id_flush': ('input', 1),
    'wb_reg_write': ('input', 1), 'wb_rd': ('input', 5), 'wb_data': ('input', 32),
    'dbg_reg_addr': ('input', 5), 'id_valid': ('output', 1),
    'id_rs1': ('output', 5), 'id_rs2': ('output', 5),
    'id_use_rs1': ('output', 1), 'id_use_rs2': ('output', 1), 'id_ecall': ('output', 1),
    'id_ex_valid': ('output', 1), 'id_ex_mem_read': ('output', 1),
    'id_ex_rd': ('output', 5), 'id_ex_insn': ('output', 32),
}
HAZARD_REQUIRED = {
    'clk': ('input', 1), 'rst_n': ('input', 1),
    'id_ex_valid': ('input', 1), 'id_ex_mem_read': ('input', 1), 'id_ex_rd': ('input', 5),
    'id_valid': ('input', 1), 'id_rs1': ('input', 5), 'id_rs2': ('input', 5),
    'id_use_rs1': ('input', 1), 'id_use_rs2': ('input', 1), 'id_ecall': ('input', 1),
    'ex_redirect_valid': ('input', 1), 'mem_stall': ('input', 1),
    'if_stall': ('output', 1), 'if_flush': ('output', 1), 'id_stall': ('output', 1),
    'id_flush': ('output', 1), 'ex_stall': ('output', 1),
    'halt_pending': ('output', 1), 'flush_event': ('output', 1),
}


def _module_ports(source: str, name: str) -> dict[str, tuple[str, int]]:
    header = extract_module_header(source, name)
    found: dict[str, tuple[str, int]] = {}
    direction = None
    width = 1
    for port in _split_ports(header['interfaces']):
        name_match = re.search(r'([A-Za-z_][A-Za-z0-9_$]*)\s*$', port)
        if not name_match:
            raise ValueError(f'{name} has an unsupported port declaration')
        port_name = name_match.group(1)
        direction_match = re.match(r'\s*(input|output|inout)\b', port)
        if direction_match:
            direction = direction_match.group(1)
            packed = re.findall(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', port)
            if ('[' in port and not packed) or len(packed) > 1:
                raise ValueError(f'{name}.{port_name} has unsupported width')
            width = abs(int(packed[0][0]) - int(packed[0][1])) + 1 if packed else 1
        if direction is None or port_name in found:
            raise ValueError(f'{name} has duplicate or unspecified ports')
        found[port_name] = (direction, width)
    return found


def _instance_connections(source: str, module_name: str) -> dict[str, str]:
    # Only plain, named, unparameterized single instances are recognized. More
    # complicated topologies remain not_covered instead of guessing wiring.
    source = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/', ' ', source)
    pattern = r'\b' + re.escape(module_name) + r'\s+[A-Za-z_][A-Za-z0-9_$]*\s*\('
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise ValueError(f'top must instantiate exactly one plain {module_name}')
    start = matches[0].end() - 1
    content, _ = _group(source, start)
    connections: dict[str, str] = {}
    for item in _split_ports(content):
        match = re.fullmatch(r'\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(\s*([A-Za-z_][A-Za-z0-9_$]*)\s*\)', item)
        if not match or match.group(1) in connections:
            # Many unrelated ports legitimately contain constants/expressions;
            # leave them unrecognized rather than rejecting the entire design.
            continue
        connections[match.group(1)] = match.group(2)
    return connections



def _redirect_is_gated(plan: dict[str, Any], files: dict[str, str]) -> tuple[bool | None, str]:
    """Recognize actual top wiring so the IF probe does not guess a gate."""
    modules = {m.get('name'): m.get('file') for m in plan.get('modules', []) if isinstance(m, dict)}
    top = files.get(modules.get(plan.get('top_module')), '')
    source = files.get(modules.get('if_stage'), '')
    required = {'clk': ('input', 1), 'rst_n': ('input', 1), 'if_stall': ('input', 1),
                'if_flush': ('input', 1), 'redirect_valid': ('input', 1), 'redirect_pc': ('input', 32),
                'cpu_req_valid': ('output', 1), 'cpu_req_addr': ('output', 32),
                'cpu_req_ready': ('input', 1), 'cpu_resp_valid': ('input', 1),
                'cpu_resp_data': ('input', 32)}
    try:
        ports = _module_ports(source, 'if_stage')
        if any(ports.get(name) != spec for name, spec in required.items()):
            raise ValueError('IF 接口不属于该探针支持的架构')
        if any(kind in {'input', 'inout'} and name not in required for name, (kind, _) in ports.items()):
            raise ValueError('IF 含未知输入')
        clean = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/', ' ', top)
        matches = list(re.finditer(r'\bif_stage\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(', clean))
        if len(matches) != 1:
            raise ValueError('无法唯一定位 IF 实例')
        content, _ = _group(clean, matches[0].end() - 1)
        exprs = []
        for item in _split_ports(content):
            match = re.fullmatch(r'\.redirect_valid\s*\((.*)\)', item, re.DOTALL)
            if match:
                exprs.append(match.group(1).strip())
        if len(exprs) != 1:
            raise ValueError('IF redirect 连接不明确')
        hazard = _instance_connections(clean, 'hazard_unit')
        redirect, stall = hazard.get('ex_redirect_valid'), hazard.get('mem_stall')
        if not redirect or not stall:
            raise ValueError('hazard 的 redirect 或 MEM stall 连接不明确')
        expr = exprs[0]
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', expr) and expr != redirect:
            aliases = re.findall(r'\bassign\s+' + re.escape(expr) + r'\s*=\s*([^;]+);', clean)
            if len(aliases) != 1:
                raise ValueError('IF redirect 信号的表达式不明确')
            expr = aliases[0]
        compact = re.sub(r'[\s()]', '', expr)
        if compact == redirect:
            return False, ''
        guarded = {left + operator + right
                   for operator in ('&&', '&')
                   for negation in ('!', '~')
                   for left, right in ((redirect, negation + stall), (negation + stall, redirect))}
        if compact in guarded:
            return True, ''
        raise ValueError('IF redirect 门控表达式不受支持')
    except (ValueError, TypeError) as error:
        return None, f'IF redirect/MEM stall 连接无法确认：{error}'


def _recognize_topology(plan: dict[str, Any], files: dict[str, str]) -> tuple[bool, str, bool]:
    modules = plan.get('modules') if isinstance(plan, dict) else None
    if not isinstance(modules, list):
        return False, '计划中缺少模块列表', False
    selected: dict[str, str] = {}
    for name in ('id_stage', 'hazard_unit', 'if_stage', 'ex_stage', 'mem_stage', plan.get('top_module')):
        if not isinstance(name, str):
            return False, '计划中缺少顶层模块', False
        matches = [item for item in modules if isinstance(item, dict) and item.get('name') == name]
        if len(matches) != 1 or not isinstance(matches[0].get('file'), str):
            return False, f'不能唯一定位 {name}', False
        content = files.get(matches[0]['file'])
        if not isinstance(content, str):
            return False, f'RTL 清单缺少 {name}', False
        selected[name] = content
    try:
        id_ports = _module_ports(selected['id_stage'], 'id_stage')
        hazard_ports = _module_ports(selected['hazard_unit'], 'hazard_unit')
        for name, expected in ID_REQUIRED.items():
            if id_ports.get(name) != expected:
                return False, f'ID 接口 {name} 不属于该探针支持的架构', False
        for name, expected in HAZARD_REQUIRED.items():
            if hazard_ports.get(name) != expected:
                return False, f'hazard 接口 {name} 不属于该探针支持的架构', False
        for name, (kind, width) in id_ports.items():
            if kind in {'input', 'inout'} and name not in ID_REQUIRED and name != 'mem_stall':
                return False, f'ID 有未知输入 {name}，不安全的假设将被避免', False
        if 'mem_stall' in id_ports and id_ports['mem_stall'] != ('input', 1):
            return False, 'ID mem_stall 接口不受支持', False
        for name, (kind, width) in hazard_ports.items():
            if kind in {'input', 'inout'} and name not in HAZARD_REQUIRED:
                return False, f'hazard 有未知输入 {name}，不安全的假设将被避免', False
        top = selected[plan['top_module']]
        conn = {name: _instance_connections(top, name) for name in
                ('id_stage', 'hazard_unit', 'if_stage', 'ex_stage', 'mem_stage')}
        def same(first: str, second: str, port: str) -> None:
            if not conn[first].get(port) or conn[first].get(port) != conn[second].get(port):
                raise ValueError(f'{first}/{second}.{port} are not directly connected')
        for port in ('clk', 'rst_n', 'id_stall', 'id_flush', 'id_valid', 'id_rs1', 'id_rs2',
                     'id_use_rs1', 'id_use_rs2', 'id_ecall', 'id_ex_valid', 'id_ex_mem_read', 'id_ex_rd'):
            same('id_stage', 'hazard_unit', port)
        for port in ('if_id_valid', 'if_id_pc', 'if_id_insn'):
            same('id_stage', 'if_stage', port)
        for port in ('clk', 'rst_n', 'if_stall', 'if_flush'):
            same('hazard_unit', 'if_stage', port)
        for port in ('id_ex_valid', 'id_ex_insn', 'id_ex_mem_read', 'id_ex_rd'):
            same('id_stage', 'ex_stage', port)
        for port in ('ex_stall', 'ex_redirect_valid'):
            same('hazard_unit', 'ex_stage', port)
        same('hazard_unit', 'mem_stage', 'mem_stall')
        if 'mem_stall' in id_ports:
            same('id_stage', 'hazard_unit', 'mem_stall')
    except ValueError as error:
        return False, f'ID/hazard 顶层接口或连接无法确认：{error}', False
    return True, '', 'mem_stall' in id_ports


def run_l1_id_hazard_probe(*, plan: dict[str, Any], files: dict[str, str], combined_path: Path,
                           output_dir: Path, timeout_seconds: int = 20) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ('compile.log', 'simulation.log'):
        path = output_dir / name
        if path.is_file():
            path.unlink()
    result: dict[str, Any] = {'name': PROBE_NAME, 'status': 'not_covered', 'passed': None}
    supported, reason, id_mem_stall = _recognize_topology(plan, files)
    if not supported:
        result['detail'] = f'该 ID/hazard 组合探针未覆盖此实现：{reason}'
        return result
    redirect_gated, reason = _redirect_is_gated(plan, files)
    if redirect_gated is None:
        result['detail'] = reason
        return result
    if not PROBE_TB.is_file():
        result.update(status='error', passed=False, detail='ID/hazard 定向测试平台不存在。')
        return result
    with tempfile.TemporaryDirectory(prefix='eda-l1-id-hazard-') as tmp:
        executable = Path(tmp) / 'probe.vvp'
        command = ['iverilog', '-g2012']
        if id_mem_stall:
            command.append('-DL1_ID_HAS_MEM_STALL')
        if redirect_gated:
            command.append('-DL1_IF_REDIRECT_GATED')
        command += ['-s', 'tb_l1_id_hazard', '-o', str(executable), str(PROBE_TB), str(combined_path)]
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            (output_dir / 'compile.log').write_text(compiled.stdout + compiled.stderr, encoding='utf-8')
            if compiled.returncode:
                result.update(status='error', passed=False, detail='ID/hazard 定向验证无法编译；请查看 compile.log。',
                              return_code=compiled.returncode)
                return result
            simulated = subprocess.run(['vvp', str(executable)], capture_output=True, text=True,
                                       timeout=timeout_seconds, check=False)
            (output_dir / 'simulation.log').write_text(simulated.stdout + simulated.stderr, encoding='utf-8')
        except FileNotFoundError as error:
            result.update(status='error', passed=False, detail=f'ID/hazard 验证工具不可用：{error.filename}')
            return result
        except subprocess.TimeoutExpired:
            result.update(status='error', passed=False, detail=f'ID/hazard 验证超过 {timeout_seconds} 秒')
            return result
    output = simulated.stdout + simulated.stderr
    result['return_code'] = simulated.returncode
    if simulated.returncode == 0 and PASS_MARKER in output:
        result.update(status='passed', passed=True, detail='MEM stall 保持、load-use bubble、redirect 同拍保持、IF 请求稳定及 ECALL 单次提交通过。')
        return result
    matches = re.findall(r'CHECK:\s*([^\s—]+)\s*—\s*([^\r\n]+)', output)
    if matches:
        result.update(status='failed', passed=False, checks=[{'name': name, 'detail': detail.strip()} for name, detail in matches])
        result['detail'] = '; '.join(f'{name}: {detail.strip()}' for name, detail in matches)
    else:
        result.update(status='error', passed=False, detail='ID/hazard 未产生有效结果；请查看 simulation.log。')
    return result


def add_l1_id_hazard_to_report(report: dict[str, Any], probe: dict[str, Any], *, required: bool = False) -> None:
    if required and probe.get('status') == 'not_covered':
        probe = dict(probe, status='error', passed=False, detail='原本可执行的 ID/hazard 检查不再适用；无法验证当前修复：' + str(probe.get('detail') or ''))
    if not isinstance(report.get('directed_checks'), list):
        report['directed_checks'] = []
    report['directed_checks'].append(probe)
    if not isinstance(report.get('test_suites'), list):
        report['test_suites'] = []
    status = probe.get('status')
    passed = status == 'passed' and probe.get('passed') is True
    not_covered = status == 'not_covered'
    report['test_suites'].append({'name': PROBE_NAME, 'passed': passed, 'skipped': not_covered,
                                  'checks': len(probe.get('checks') or []) or 1, 'status': status})
    if not passed and not not_covered:
        report['passed'] = False
        if not isinstance(report.get('checks'), list):
            report['checks'] = []
        checks = probe.get('checks')
        if not isinstance(checks, list) or not checks:
            checks = [{'name': PROBE_NAME, 'detail': str(probe.get('detail') or '定向验证未完成')}]
        report['checks'][0:0] = checks
