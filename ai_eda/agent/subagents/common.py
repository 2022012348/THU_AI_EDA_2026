"""Parser / Planner / Coder / Tester / Modifier 共用的协议与工具函数。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_eda.agent.reporting import report_summary, stage_label

PARSER_SYSTEM_PROMPT = """You are the Spec Parser of a digital IC design agent.
Decide whether the given design spec (plus user supplements and previous parser addendum) is sufficient to implement, plan, and verify the design.
Your job is to SUPPLEMENT and CORRECT the original spec, never to summarize or replace it.

Blocking gaps (ask the user):
- missing/contradictory top-level ports, clock/reset, ISA behavior, external bus handshake, ECALL/halt behavior, file/task structure, or externally observable test expectations;
- requirements that make a correct implementation impossible or make PASS depend on an undefined architectural choice.

Non-blocking details (do NOT ask; record short assumptions in spec_addendum instead):
- internal module port names, internal handshake/FSM/state encoding details;
- Cache refill arbitration, epoch bit-width/implementation, internal buffers/queues, predictor table encoding;
- ROB/rename/issue implementation details not externally observable;
- optional auxiliary file names or internal RAM implementation choices.
These belong to Planner/Coder/Modifier and may be frozen later; do not block the flow on them.

When only non-blocking gaps remain, set sufficient=true, missing=[], questions=[], and put concise assumptions in spec_addendum.
Keep every original requirement intact. Return ONLY a JSON object:
{"sufficient": true|false, "missing": ["..."], "questions": ["..."], "spec_addendum": "only additional/corrected requirements or assumptions in Markdown; empty if none"}
Do not put the full original spec in spec_addendum. Do not return Markdown fences or extra text."""

PLANNER_SYSTEM_PROMPT = """You are the RTL Planner of a digital IC design agent.
Given the frozen spec, plan the project module and file structure. The agent will write each file separately.
Return ONLY a JSON object:
{"project_name": "...", "top_module": "...", "modules": [{"name": "module_name", "file": "rtl/module_name.sv", "description": "short responsibility", "interfaces": "complete port contract: every port name, direction and width; for each inter-module signal use the same name/width in all modules"}], "notes": "..."}
Use only relative paths ending in .sv. Every module must be implementable in one file. The interfaces field is the interface contract: list every port name, direction and width, and use identical names/widths for a signal in every module. Do not return Markdown fences or extra text."""

RV32I_L1_CODE_PATTERNS = """RV32I design review guidance (the frozen Spec and the plan's explicit interfaces/encodings take precedence):
- Preserve accepted one-cycle cache/bus responses across downstream stalls. If a response arrives when a pipeline register cannot advance, buffer it or apply an equivalent protocol-safe mechanism; do not overwrite a held valid instruction.
- For the L1 external bus specified in A.1, read data is sampled on the clock edge where valid && ready. If top-level wiring says mem_resp_valid = mem_req_valid && mem_req_ready, both indicate that SAME accepting edge; a combinational high before the edge does not by itself mean a previous-word response. Derive timing from the actual producer/consumer RTL; do not invent a delayed response.
- Track each accepted IF-to-I-cache request until its single response is consumed or invalidated. Do not issue another fetch for the same PC merely because the request-valid bit cleared at acceptance; bind response data to the accepted request's PC, including stalls and redirects.
- Distinguish a load-use interlock (hold the dependent instruction and insert a bubble into EX while the older load progresses) from a downstream memory/structural stall (hold valid older instructions until they can advance). Apply reset and redirect priorities from the Spec.
- Forward from the youngest eligible older producer; an EX/MEM load cannot forward its address as load data. Follow the plan's encoding for forwarding selectors. JAL/JALR link results forward PC+4.
- For a 128-bit line, word wsel begins at bit wsel*32. For Icarus compatibility, read an unpacked array element into an intermediate 128-bit vector before selecting its word; avoid a dynamic part-select directly on a variable-indexed array element. Preserve byte offsets, little-endian lane selection, sign/zero extension and write byte enables.
- When the Spec requires write-allocate, a store miss refills the target line, merges the store bytes and performs exactly one write-through; acknowledge and retire only after external acceptance.
- Handle reset, redirects and ECALL without revoking an already asserted unaccepted external request except when the Spec explicitly permits it. When the Spec requires wrong-path or stale-epoch refills to be discarded, do not install the line or deliver its response. Use the current response for the final refill word.
- On an I-cache cold miss, trace the accepted request's saved word offset through refill and response: requested words 0/1/2/3 must return the corresponding address's data. In a nonblocking-assignment refill, the buffer element for the final beat still contains its old value on that edge; if responding on that edge, the final word must come from the current accepted bus data. Treat this as a hypothesis to verify against the current RTL, not as an assumed failure.
- Trace ECALL valid and the associated PC/instruction through ID, EX, MEM and retirement. If a hazard or halt-pending freezes ID, check whether the same-cycle stall/flush prevents ECALL from ever entering EX or emits it twice. The accepted ECALL must enter EX exactly once when downstream can accept it; freeze only younger fetches and preserve older operations. This is a hypothesis to verify, not proof that any timeout is an ECALL bug.
"""

RV32I_PIPELINE_CHECKLIST = """RV32I cross-module consistency checks:
- The producer and consumer of every ready/valid interface agree on acceptance, pulse timing, buffering, reset and stall behavior.
- Pipeline stalls, bubbles and flushes do not duplicate, drop or incorrectly retire instructions; older operations retain architectural priority.
- Forwarding, load-use hazards, branch/jump targets, store data/byte lanes, and synchronous reset follow the frozen Spec.
- Where caches are required, check complete refill, store policy, epoch/flush, invalid lines and exactly-once bus requests against the frozen Spec; do not invent an alternative store-miss or wrong-path policy.
"""

MODIFIER_SYSTEM_PROMPT = """You are the RTL Modifier of a digital IC design agent.
You work in a persistent multi-turn repair conversation. The first user message contains the frozen spec, project plan, current RTL files, and the first failure report; later user messages contain the next Tester failure and the current file snapshot.
Your job is to diagnose the root cause and modify only the files that need changes.

Rules:
- Match the Planner interfaces exactly. Never rename ports, modules, files, or parameters.
- For compile failures, fix every error in stderr, including hierarchy/port/width errors.
- Toolchain limits of `iverilog -g2012`: distinguish fatal errors from warnings. "sorry: constant selects in always_* processes are not fully supported (all bits will be included)" describes sensitivity-list broadening and alone does not reject compilation; use the compiler return code and actual errors. Enum-typed ternaries can require explicit casts; nested range part-selects must be split into intermediate vectors when rejected.
- For simulation failures, use the failing checks and trace to find the root cause; do not guess or weaken behavior.
- Preserve already-correct logic. A small targeted patch is better than rewriting the project.
- Do not add external IPs, simulation-only constructs, or modify the teacher TB.
- Keep diagnosis focused: identify the minimal root cause, avoid restating the spec or exploring unneeded alternatives.
- Group related failed checks by shared observable failure, and prioritize the earliest causal mismatch. Distinguish direct evidence from hypotheses; do not assume all failures share one root cause. Choose a small repair that can be verified before expanding the scope.
- If the same check failed in the previous repair round, do not repeat the same patch. Re-read the failing trace and change the data path or state transition that produces the mismatch.
- In notes, identify the observed evidence and the actual changed logic; do not claim that an unexecuted test passed or a hypothesis was proven. Preserve requirements for all tests even if the current patch addresses one root cause.
- Compare every returned content with the current file snapshot. At least one returned file MUST differ from the snapshot; returning an unchanged file is an invalid no-op patch.
- If a previous patch did not change behavior, do not repeat it; change the root-cause hypothesis and the implementation strategy.
- Return ONLY a JSON object; no Markdown fences, no prose outside JSON.

Return schema:
{"files": [{"path": "rtl/foo.sv", "content": "full SystemVerilog file content"}], "notes": "short diagnosis and repair summary"}
You may return only files that need changes, but each returned file must contain its complete content.

"""

RV32I_MODIFIER_RULES = """- RV32I load/store failures: explicitly verify little-endian byte lanes, sign/zero extension, SB/SH byte enables and replicated wdata, cache refill merge, write-through ordering, and load-use forwarding.
- RV32I reset/control failures: verify synchronous reset gating of dmem_valid, pipeline valid/flush, PC redirection, and halted/exit_code timing.
- Retire pc/insn mismatch: before touching stall, cache or refill logic, compare the retired instruction word against the teacher program at pc, pc-4 and pc+4 (the read-only replay reports these as expected_insn, insn_at_pc_minus4 and prev_if). If the retired word matches a neighbouring address, the defect is the pc/instruction pairing carried through the pipeline (which pc value is latched alongside the instruction, and which pc the debug retire port exposes), not the fetch protocol.
- If many tests time out waiting for halted while imem_addr advances, prioritize the ECALL→halt path: ID decode, is_ecall propagation through EX/MEM/WB, WB halted/exit_code commit, IF freeze, and synchronous reset. Do not assume a cache or load/store bug from the timeout alone.
- Fetch/response lifetime: the pc recorded with an instruction must be the address that instruction was fetched from, not the following address. Keep one outstanding request bound to the response you consume; do not advance or rebind the request address before that response has been consumed, and do not let a dropped response leave the address bookkeeping ahead of the instruction stream.
"""

MAX_PARSER_ROUNDS = 3
SV_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./-]+\.sv$")
MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def extract_json_payload(text: str) -> dict[str, Any]:
    """从模型回答中提取第一个 JSON 对象（兼容 ```json 围栏）。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    # Some models emit one valid JSON object followed by stray closing
    # delimiters. Accept only that bounded suffix; never silently accept a
    # second object or arbitrary trailing content as part of a repair.
    if raw.startswith("{"):
        try:
            payload, end_index = json.JSONDecoder().raw_decode(raw)
            suffix = raw[end_index:].strip()
            if (isinstance(payload, dict) and suffix and len(suffix) <= 16
                    and all(char in "]}" for char in suffix)):
                return payload
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(raw[start : end + 1])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    raise ValueError("模型没有返回合法的 JSON 对象")


def safe_project_path(run_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("RTL 文件路径不能为空")
    relative = relative.strip().replace("\\", "/")
    if not SV_PATH_PATTERN.fullmatch(relative):
        raise ValueError(f"RTL 文件路径必须是相对 .sv 路径：{relative}")
    project_root = (run_dir / "project").resolve()
    candidate = (project_root / relative).resolve()
    if project_root not in candidate.parents:
        raise ValueError(f"RTL 文件路径越出项目目录：{relative}")
    return candidate


def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("Planner 没有返回 modules 列表")
    clean_modules: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_files: set[str] = set()
    for item in modules:
        if not isinstance(item, dict):
            raise ValueError("Planner 的 module 条目格式无效")
        name = item.get("name")
        file = item.get("file")
        if not isinstance(name, str) or not MODULE_NAME_PATTERN.fullmatch(name):
            raise ValueError("Planner 返回了非法模块名")
        if name in seen_names:
            raise ValueError(f"Planner 重复声明模块：{name}")
        if not isinstance(file, str):
            raise ValueError("Planner 的模块缺少 file")
        file = file.strip().replace("\\", "/")
        if not SV_PATH_PATTERN.fullmatch(file):
            raise ValueError(f"Planner 返回了非法文件路径：{file}")
        if file in seen_files:
            raise ValueError(f"Planner 重复声明文件：{file}")
        seen_names.add(name)
        seen_files.add(file)
        clean_modules.append(
            {
                "name": name,
                "file": file,
                "description": str(item.get("description") or ""),
                "interfaces": str(item.get("interfaces") or ""),
            }
        )
    top_module = payload.get("top_module") or clean_modules[0]["name"]
    if not isinstance(top_module, str) or top_module not in seen_names:
        raise ValueError("Planner 的 top_module 不在 modules 中")
    return {
        "project_name": str(payload.get("project_name") or "agent_project")[:100],
        "top_module": top_module,
        "modules": clean_modules,
        "notes": str(payload.get("notes") or ""),
    }


def validate_modifier_files(payload: dict[str, Any], plan: dict[str, Any]) -> dict[str, str]:
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Modifier 没有返回 files 列表")
    allowed = {module["file"] for module in plan["modules"]}
    clean: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Modifier 的 file 条目格式无效")
        path = item.get("path")
        content = item.get("content")
        normalized = path.strip().replace("\\", "/") if isinstance(path, str) else ""
        if normalized not in allowed:
            raise ValueError(f"Modifier 返回了计划之外的文件：{path}")
        if not isinstance(content, str) or "module" not in content:
            raise ValueError(f"Modifier 为 {path} 返回的内容不是 RTL")
        clean[normalized] = content
    return clean


def combine_files(files: dict[str, str]) -> str:
    return "\n\n".join(f"// file: {path}\n{content}" for path, content in files.items()) + "\n"


def trace_mismatches(report: dict[str, Any]) -> list[str]:
    # A trace expected_* field can describe a reference calculation, not a TB
    # assertion (e.g. DFT magnitudes). Only surface evidence from failed tests.
    failed_tests = {
        str(item.get("testcase") or item.get("test") or item.get("name") or "")
        for item in report.get("checks") or [] if isinstance(item, dict)
    } - {""}
    messages: list[str] = []
    for row in report.get("trace") or []:
        if not isinstance(row, dict):
            continue
        test = str(row.get("test") or row.get("testcase") or "")
        if test and test not in failed_tests:
            continue
        differences = []
        for key, value in row.items():
            if not key.startswith("expected_"):
                continue
            if not test and not any(k in row for k in (f"actual_{key[9:]}", f"out_{key[9:]}")):
                continue
            actual_key = key.removeprefix("expected_")
            actual = row.get(f"actual_{actual_key}")
            if actual is None:
                actual = row.get(actual_key)
            if actual is None:
                actual = row.get(f"out_{actual_key}")
            if actual is not None and str(actual) != str(value):
                differences.append(f"{actual_key}={actual} (expected {value})")
        if differences:
            label = row.get("event") or row.get("case") or "sample"
            messages.append(f"cycle {row.get('cycle', '?')} · {label}: " + "，".join(differences))
    return messages[:12]


def _retire_pairing_summary(observation: dict[str, Any]) -> str:
    """机械统计：退休的指令字与 pc / pc-4 处程序内容的重合次数。"""
    items = [item for item in (observation.get('observations') or []) if isinstance(item, dict)]
    if not items:
        return ""
    def same(item: dict[str, Any], key: str) -> bool:
        value = item.get(key)
        return isinstance(value, str) and bool(value) and value.lower() == str(item.get('insn') or '').lower()
    at_pc = sum(same(item, 'expected_insn') for item in items)
    at_minus4 = sum(same(item, 'insn_at_pc_minus4') for item in items)
    return (
        f"Retire pairing summary (counts computed from the read-only replay, not an acceptance result): "
        f"{len(items)} mismatches; retired word equals the program word at pc in {at_pc} and at pc-4 in {at_minus4}."
    )


def report_feedback(report: dict[str, Any] | None) -> str:
    if report is None:
        return "Verification has not run for the previous round."
    if report.get("passed"):
        return "The previous teacher TB passed; preserve current behavior and finish the remaining steps."
    lines = [report_summary(report)]
    if isinstance(report.get('repair_ticket'),dict):
        lines.append('This round has ONE repair ticket. Explain this counterexample; unrelated symptoms are deferred. '
                     'Request a probe if needed. Return its exact ticket_id with your edits:\n'
                     + json.dumps(report['repair_ticket'],ensure_ascii=False))
        if report['repair_ticket'].get('pipeline_token_presence'):
            lines.append('Use the retained pipeline history to locate the last stage where the expected PC-tag was actually valid and examine its transfer into the next stage, including stall/flush and request ownership. Stage presence is bounded observation, not proof of which module is faulty.')
    bus = report.get('data_bus_observation')
    if isinstance(bus, dict):
        failing = {str(c.get('name')) for c in report.get('checks', []) if isinstance(c, dict)}
        selected = [row for row in bus.get('tests', []) if row.get('test') in failing][:6]
        lines.append('Read-only data bus evidence: ' + json.dumps(
            {'status': bus.get('status'), 'scope': bus.get('scope'), 'tests': selected}, ensure_ascii=False))
    if isinstance(report.get('retirement_observation'), dict):
        lines.append('Read-only retirement replay evidence: ' + json.dumps(report['retirement_observation'], ensure_ascii=False))
        pairing = _retire_pairing_summary(report['retirement_observation'])
        if pairing:
            lines.append(pairing)
    tail = report.get('retire_tail')
    if isinstance(tail, dict) and tail.get('status') == 'observed':
        summary = tail.get('summary') or {}
        lines.append(
            'Read-only retire tail at end of simulation: '
            f"total_retirements={summary.get('total')} halted={summary.get('halted')} "
            f"exit_code={summary.get('exit')} last_test={summary.get('test')}. "
            'Repeated adjacent PCs may be legitimate loops; compare instruction semantics and side effects before diagnosing duplicate execution. '
            f"Recent pc sequence: {str(tail.get('loop') or '')[:600]}"
        )
    for probe in (report.get('directed_checks') or [])[:6]:
        if isinstance(probe, dict):
            lines.append('Automatic directed evidence: ' + json.dumps({
                'name': probe.get('name'), 'status': probe.get('status'),
                'detail': probe.get('detail'), 'observations': probe.get('observations') or []}, ensure_ascii=False))
    structural = report.get('structural_diagnostics')
    if isinstance(structural, dict) and structural.get('issues'):
        lines.append('Yosys static structural evidence (not a behavioral root-cause verdict):')
        lines.extend('- ' + str(issue) for issue in structural['issues'][:16])
    if report.get('teacher_passed') is False and report.get('directed_checks'):
        lines.append(
            'Evidence scope: the original teacher TB still fails. Independent directed probes test specific boundaries; '
            'do not infer that a probe failure explains unrelated arithmetic, forwarding or retirement errors. '
            'Find the earliest architectural mismatch in the teacher trace and trace the actual producing signals; '
            'track directed-probe failures separately. Do not simply choose the first listed check as the root cause.')
    mismatches = trace_mismatches(report)
    if mismatches:
        lines.append("Failing cycles:")
        lines.extend(f"- {item}" for item in mismatches[:12])
    suites = [
        item.get("name") for item in (report.get("test_suites") or [])
        if item.get("name") and not item.get("passed") and not item.get("skipped")
    ]
    if suites:
        lines.append("Failing suites: " + ", ".join(suites))
    checks = report.get("checks") or []
    if report.get('partial_output'):
        lines.append('Partial simulation output: trace is sampled and repeated failures are counted; the suite did not finish. '
                     + json.dumps(report.get('diagnostic_counts') or {}, ensure_ascii=False))
    elif report.get('diagnostic_counts'):
        lines.append('Completed simulation: trace samples and grouped failure counts; full output is retained separately. '
                     + json.dumps(report['diagnostic_counts'], ensure_ascii=False))
    if checks:
        # Repeated assertions in one testcase can otherwise crowd every other
        # failure out of the prompt. Count identical records and show one item
        # per testcase first, then additional distinct details within the cap.
        groups: dict[str, dict[str, int]] = {}
        for item in checks:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "check")
            detail = str(item.get("detail") or "")
            details = groups.setdefault(name, {})
            count = item.get('count', 1)
            count = count if type(count) is int and count > 0 else 1
            details[detail] = details.get(detail, 0) + count
        lines.append("Failed checks (grouped; repeated occurrences counted):")
        selected: list[tuple[str, str, int]] = []
        per_test = {name: list(details.items()) for name, details in groups.items()}
        for name, details in per_test.items():
            if len(selected) >= 20:
                break
            detail, count = details[0]
            selected.append((name, detail, count))
        # Reserve room for another distinct symptom (e.g. halt timeout after
        # an earlier retire mismatch) even when many tests failed.
        if len(per_test) > 18:
            selected = selected[:18]
        for name, details in per_test.items():
            for detail, count in details[1:]:
                if len(selected) >= 20:
                    break
                selected.append((name, detail, count))
            if len(selected) >= 20:
                break
        for name, detail, count in selected:
            suffix = f" (×{count})" if count > 1 else ""
            lines.append(f"- {name}: {detail}{suffix}".rstrip(": "))
        shown = sum(count for _, _, count in selected)
        total_occurrences = sum(sum(details.values()) for details in groups.values())
        if total_occurrences > shown:
            lines.append(f"- ... {total_occurrences - shown} additional occurrences omitted; see full report")
        timeout_count = sum("等待 halted 超时" in str(item.get("detail") or "") for item in checks)
        has_retire_mismatch = any(
            "retire PC/instruction does not match" in str(item.get("detail") or "")
            for item in checks if isinstance(item, dict)
        )
        if (report.get("stage") == "simulation" and timeout_count >= 2
                and (timeout_count * 2 > len(checks) or has_retire_mismatch)):
            lines.append(
                "HALT-TIMEOUT：多个测试等待 halted 超时；这不能单独确定根因。"
                "结合各失败测试 trace 检查 resp_valid 捕获、stall/valid、ECALL 到 WB 的传递与提交；"
                "同时排查前递、访存握手和控制重定向，不要仅凭超时断定 halt 或 Cache 有错。"
                "逐拍核对：refill 后返回的是原请求的 word offset（不是总返回最后一字）；"
                "无更老指令重定向且下游可接收时，检查 ID stall/flush 是否误清 ECALL，能否使其进入 EX 一次。"
            )
    if report.get("stage") == "simulation" and checks:
        joined = "\n".join(f"{item.get('name')}: {item.get('detail', '')}" for item in checks)
        if "retire PC/instruction does not match" in joined:
            lines.append(
                "FETCH/RETIRE 诊断候选：逐拍对照已接受取指的 PC、原始指令、ICache cold miss 的请求字偏移与退休值；"
                "分别检查四种 word offset、最后一字的非阻塞赋值，以及重复请求/响应绑定。"
                "若同时存在 halt 超时，也要独立核对 ECALL 是否能从 ID 进入 EX；这些是待验证的假设。"
            )
        if "cache_instruction_reuse" in joined or "imem 请求" in joined or "I-memory request changed" in joined:
            lines.append(
                "ICACHE/REFILL: 对已发出的请求检查 valid/addr 与 ready 握手；重定向或 epoch 失效时，"
                "按 Spec 处理在途事务并丢弃错误路径响应，勿将无效 refill 安装为有效行。"
            )
    if report.get("stage") == "compile":
        detail = (report.get("stderr") or report.get("stdout") or "").strip()
        if detail:
            # Icarus emits many nonfatal "sorry" warnings; the actual error may
            # occur far above the tail. Preserve it separately for the Modifier.
            errors = [line for line in detail.splitlines()
                      if re.search(r"\b(?:error|fatal)\s*:", line, re.IGNORECASE)]
            if errors:
                lines.append("Compiler errors (first 30):")
                lines.extend(errors[:30])
                if len(errors) > 30:
                    lines.append(f"... {len(errors) - 30} additional errors omitted")
            lines.append("Compiler output (tail):")
            lines.append(detail[-3000:])
    return "\n".join(lines)


def project_feedback(files: dict[str, str], plan: dict[str, Any], report: dict[str, Any]) -> str:
    lines = [report_summary(report), "当前项目文件："]
    lines.extend(f"- {path} ({len(content)} chars)" for path, content in files.items())
    lines.append("计划模块：")
    lines.extend(f"- {module['name']} -> {module['file']}" for module in plan["modules"])
    lines.append("")
    lines.append(report_feedback(report))
    return "\n".join(lines)
