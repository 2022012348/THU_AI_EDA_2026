"""只读探针：记录仿真结束前最后 N 条退休指令。

教师 TB 超时时只报"等待 halted 超时 + 固定 imem_addr"，模型看不到 CPU
到底卡在哪个循环里。这里另起一个顶层模块，跟随同一个教师 TB 采样
``dbg_retire_valid``，用环形缓冲保存最近 N 条 (pc, insn)，在 ``final``
块里一次性打印。它不改变 TB、不改 DUT、也不参与验收判定。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ai_eda.rtl.runner import _cpu_feature_compile_flags

MARKER = "AI_EDA_RETIRE_TAIL|"
DEPTH = 48

PROBE = (
    "`timescale 1ns/1ps\n"
    "module agent_retire_tail;\n"
    "  localparam integer DEPTH = " + str(DEPTH) + ";\n"
    "  reg [31:0] pcs [0:DEPTH-1];\n"
    "  reg [31:0] insns [0:DEPTH-1];\n"
    "  integer head = 0;\n"
    "  integer total = 0;\n"
    "  integer i;\n"
    "  integer start;\n"
    "  always @(posedge tb_agent_rv32i5.u_teacher_tb.clk) begin\n"
    "    if (tb_agent_rv32i5.u_teacher_tb.rst_n && tb_agent_rv32i5.u_teacher_tb.dbg_retire_valid) begin\n"
    "      pcs[head] = tb_agent_rv32i5.u_teacher_tb.dbg_retire_pc;\n"
    "      insns[head] = tb_agent_rv32i5.u_teacher_tb.dbg_retire_insn;\n"
    "      head = (head + 1) % DEPTH;\n"
    "      total = total + 1;\n"
    "    end\n"
    "  end\n"
    "  final begin\n"
    "    $display(\"AI_EDA_RETIRE_TAIL|summary=1|total=%0d|halted=%b|exit=%h|test=%s\", total,\n"
    "      tb_agent_rv32i5.u_teacher_tb.halted, tb_agent_rv32i5.u_teacher_tb.exit_code,\n"
    "      tb_agent_rv32i5.u_teacher_tb.cur_test);\n"
    "    start = (total > DEPTH) ? head : 0;\n"
    "    for (i = 0; i < DEPTH; i = i + 1) begin\n"
    "      if (total > DEPTH || i < total)\n"
    "        $display(\"AI_EDA_RETIRE_TAIL|pc=%h|insn=%h\",\n"
    "          pcs[(start + i) % DEPTH], insns[(start + i) % DEPTH]);\n"
    "    end\n"
    "  end\n"
    "endmodule\n"
)


def _compress(tail: list[dict[str, str]]) -> str:
    """把连续相同的 pc 折叠成 ``pc xN``，便于模型快速看出循环体。"""
    if not tail:
        return ""
    parts: list[str] = []
    last_pc = tail[0].get("pc", "?")
    count = 1
    for item in tail[1:]:
        pc = item.get("pc", "?")
        if pc == last_pc:
            count += 1
            continue
        parts.append(f"0x{last_pc}" + (f" x{count}" if count > 1 else ""))
        last_pc, count = pc, 1
    parts.append(f"0x{last_pc}" + (f" x{count}" if count > 1 else ""))
    return " → ".join(parts)


def capture_retire_tail(
    *, project: dict[str, Any], combined_path: Path, output_dir: Path, limit: int = DEPTH
) -> dict[str, Any]:
    """运行只读重放并返回最后若干条退休记录。"""
    if project.get("testbench_top") != "tb_agent_rv32i5":
        return {"status": "not_covered", "tail": [], "detail": "shared teacher hierarchy not recognized"}
    output_dir.mkdir(parents=True, exist_ok=True)
    probe = output_dir / "retire_tail.sv"
    probe.write_text(PROBE, encoding="utf-8")
    teacher = Path(project["testbench_path"])
    result: dict[str, Any] = {"status": "not_observed", "tail": [], "summary": {}}
    timeout = int(project.get("timeout_seconds", 120)) + 30
    with tempfile.TemporaryDirectory(prefix="eda-retire-tail-") as tmp:
        binary = Path(tmp) / "probe.vvp"
        command = [
            "iverilog", "-g2012", *_cpu_feature_compile_flags(combined_path),
            "-I", str(teacher.parent),
            "-s", "tb_agent_rv32i5", "-s", "agent_retire_tail", "-o", str(binary),
            str(teacher), str(combined_path), str(probe),
        ]
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
            (output_dir / "compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
            if compiled.returncode:
                return dict(result, status="error", detail="tail probe did not compile")
            replay = ["vvp", str(binary)]
            if project.get("expected_cpu_level") is not None:
                replay.append("+expected_cpu_level=" + str(project["expected_cpu_level"]))
            simulated = subprocess.run(replay, capture_output=True, text=True, timeout=timeout, check=False)
            output = simulated.stdout + simulated.stderr
        except subprocess.TimeoutExpired:
            return dict(result, status="timeout", detail="tail replay exceeded the wall-clock budget")
        except FileNotFoundError:
            return dict(result, status="unavailable", detail="Icarus tools unavailable")
    (output_dir / "simulation.log").write_text(output, encoding="utf-8")
    for line in output.splitlines():
        if not line.startswith(MARKER):
            continue
        fields = {}
        for item in line[len(MARKER):].split("|"):
            key, separator, value = item.partition("=")
            if separator:
                fields[key.strip()] = value.strip()
        if fields.pop("summary", None):
            result["summary"] = fields
            continue
        result["tail"].append(fields)
    if result["tail"]:
        result["status"] = "observed"
        result["tail"] = result["tail"][-limit:]
        result["loop"] = _compress(result["tail"])
    return result
