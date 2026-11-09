"""Black-box L1 I-cache redirect check against the frozen internal contract.

This adds an independent, directed simulation; it never edits or replaces the
teacher testbench. Unsupported interfaces and tool failures are explicit.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ai_eda.agent.rtl_contracts import _split_ports, extract_module_header
from ai_eda.config import AGENT_CONTENT_ROOT

PROBE_TB = AGENT_CONTENT_ROOT / "verification" / "icache_flush_edge_tb.sv"
PROBE_NAME = "l1_icache_flush_edge"
PASS_MARKER = "L1_ICACHE_FLUSH_EDGE_PASS"

# Internal standard ports from L1 spec B.4. Extra inputs cannot safely be tied
# off without knowing their semantics, so only a documented halted input is
# accepted. Additional outputs do not affect stimulus.
_REQUIRED = {
    "clk": ("input", 1), "rst_n": ("input", 1),
    "flush": ("input", 1), "flush_epoch": ("input", 2),
    "cpu_req_valid": ("input", 1), "cpu_req_addr": ("input", 32),
    "cpu_req_ready": ("output", 1), "cpu_resp_valid": ("output", 1),
    "cpu_resp_data": ("output", 32), "mem_req_valid": ("output", 1),
    "mem_req_ready": ("input", 1), "mem_req_addr": ("output", 32),
    "mem_resp_valid": ("input", 1), "mem_resp_data": ("input", 32),
}


def _supported_ports(source: str) -> tuple[bool, str, bool]:
    try:
        header = extract_module_header(source, "icache")
        ports = _split_ports(header["interfaces"])
        found: dict[str, tuple[str, int]] = {}
        direction: str | None = None
        width = 1
        for port in ports:
            name_match = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)\s*$", port)
            if not name_match:
                raise ValueError("port name or unpacked/default declaration is unsupported")
            name = name_match.group(1)
            direction_match = re.match(r"\s*(input|output|inout)\b", port)
            if direction_match:
                direction = direction_match.group(1)
                packed = re.findall(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", port)
                if "[" in port and not packed or len(packed) > 1:
                    raise ValueError(f"port {name} has a nonconstant or multidimensional width")
                width = abs(int(packed[0][0]) - int(packed[0][1])) + 1 if packed else 1
            if direction is None:
                raise ValueError("port direction missing")
            found[name] = (direction, width)
    except ValueError as error:
        return False, f"icache 端口声明无法安全识别：{error}", False
    for name, contract in _REQUIRED.items():
        if found.get(name) != contract:
            return False, f"icache 端口 {name} 不符合 B.4 标准接口：需要 {contract}，实际 {found.get(name)}", False
    extras = sorted(name for name, (kind, _) in found.items()
                    if kind in {"input", "inout"} and name not in _REQUIRED and name != "halted")
    if extras:
        return False, "icache 含未知输入，无法安全构造黑盒激励：" + ", ".join(extras), False
    if "halted" in found and found["halted"] != ("input", 1):
        return False, "icache 的 halted 端口不符合预期输入", False
    return True, "", "halted" in found


def run_l1_icache_flush_probe(
    *, plan: dict[str, Any], files: dict[str, str], combined_path: Path,
    output_dir: Path, timeout_seconds: int = 20,
) -> dict[str, Any]:
    """Run a deterministic edge test or report why it cannot be evaluated."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("compile.log", "simulation.log"):
        old_log = output_dir / filename
        if old_log.is_file():
            old_log.unlink()
    result: dict[str, Any] = {"name": PROBE_NAME, "status": "unsupported", "passed": False}
    modules = plan.get("modules") if isinstance(plan, dict) else None
    matches = [item for item in (modules or []) if isinstance(item, dict) and item.get("name") == "icache"]
    if len(matches) != 1 or not isinstance(matches[0].get("file"), str):
        result["detail"] = "计划没有唯一的 icache 模块；无法运行 L1 B.4 定向验证。"
        return result
    path = matches[0]["file"]
    source = files.get(path)
    if not isinstance(source, str):
        result["detail"] = f"RTL 清单缺少 icache 文件 {path}；无法运行定向验证。"
        return result
    supported, reason, has_halted = _supported_ports(source)
    if not supported:
        result["detail"] = reason
        return result
    if not PROBE_TB.is_file():
        result.update(status="error", detail="L1 定向测试平台不存在。")
        return result
    with tempfile.TemporaryDirectory(prefix="eda-l1-icache-probe-") as temporary:
        executable = Path(temporary) / "probe.vvp"
        command = ["iverilog", "-g2012"]
        if has_halted:
            command.append("-DL1_ICACHE_HAS_HALTED")
        command += ["-s", "tb_l1_icache_flush_edge", "-o", str(executable), str(PROBE_TB), str(combined_path)]
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            (output_dir / "compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
            if compiled.returncode:
                result.update(status="error", detail="L1 定向验证无法编译；请查看 compile.log。",
                              return_code=compiled.returncode)
                return result
            simulated = subprocess.run(["vvp", str(executable)], capture_output=True, text=True,
                                       timeout=timeout_seconds, check=False)
            (output_dir / "simulation.log").write_text(simulated.stdout + simulated.stderr, encoding="utf-8")
        except FileNotFoundError as error:
            result.update(status="error", detail=f"L1 定向验证工具不可用：{error.filename}")
            return result
        except subprocess.TimeoutExpired:
            result.update(status="error", detail=f"L1 定向验证运行超过 {timeout_seconds} 秒。")
            return result
    output = simulated.stdout + simulated.stderr
    result["return_code"] = simulated.returncode
    if 'L1_ICACHE_WORD_OFFSETS_PASS cold_offsets=4 cached_words=16' in output:
        result['observations'] = [{'name': 'icache_word_offsets', 'status': 'passed',
            'scope': 'All four cold-request word offsets and sixteen cached-word reads returned their expected data in this probe; this does not validate IF PC tagging or flush recovery.'}]
    if simulated.returncode == 0 and PASS_MARKER in output:
        result.update(status="passed", passed=True, detail="同拍 flush、旧行保留与错误路径行不命中均通过。")
        return result
    match = re.search(r"CHECK:\s*([^\s—]+)\s*—\s*([^\r\n]+)", output)
    if match:
        result.update(status="failed", check_name=match.group(1), detail=match.group(2).strip())
    else:
        result.update(status="error", detail="L1 定向验证未产生有效结果；请查看 simulation.log。")
    return result


def add_l1_icache_probe_to_report(report: dict[str, Any], probe: dict[str, Any]) -> None:
    """Preserve teacher result, but never claim overall pass with an unrun probe."""
    report["teacher_passed"] = bool(report.get("passed"))
    if not isinstance(report.get("directed_checks"), list):
        report["directed_checks"] = []
    report["directed_checks"].append(probe)
    passed = probe.get("status") == "passed" and probe.get("passed") is True
    if not isinstance(report.get("test_suites"), list):
        report["test_suites"] = []
    report["test_suites"].append({
        "name": PROBE_NAME, "passed": passed, "skipped": False, "checks": 1,
        "status": probe.get("status"),
    })
    if not passed:
        report["passed"] = False
        if report.get("stage") not in {"compile", "simulation"}:
            report["stage"] = "simulation"
        detail = str(probe.get("detail") or "L1 定向验证没有通过")
        if probe.get("status") in {"unsupported", "error"}:
            detail = "L1 定向验证未完成（不能视为通过）：" + detail
        if not isinstance(report.get("checks"), list):
            report["checks"] = []
        # This direct observation should not be hidden by hundreds of teacher
        # checks when the bounded Modifier summary selects the first cases.
        report["checks"].insert(0, {
            "name": str(probe.get("check_name") or PROBE_NAME), "detail": detail,
        })
