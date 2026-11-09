"""固定 Agent 流程的受限 EDA 自动设计执行器。

固定流水线：Parser → RTL Planner → Coder → Tester → Modifier（失败回环）。
Parser 需要补充 Spec 时通过 ``request_input`` 暂停并等待用户输入。
"""

from __future__ import annotations

import json
import hashlib
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_eda.agent.projects import get_project
from ai_eda.agent.repair_control import evaluate_repair
from ai_eda.agent.repair_candidates import build_file_ablations, restore_checkpoint
from ai_eda.agent.runs import (
    AgentCancelled,
    _now,
    _report_summary,
    _run_payload,
    _write_json,
    _write_metadata,
    agent_task_spec,
    load_agent_graph,
)
from ai_eda.agent.subagents.base import RunContext, ModelCallBudgetExceeded
from ai_eda.agent.subagents.coder import CoderAgent
from ai_eda.agent.subagents.common import safe_project_path
from ai_eda.agent.subagents.modifier import ModifierAgent, _validated_evidence, InvalidModelRepair
from ai_eda.agent.subagents.parser import ParserAgent
from ai_eda.agent.subagents.planner import PlannerAgent
from ai_eda.agent.subagents.tester import TesterAgent
from ai_eda.config import AGENT_RUNS_ROOT

EventSink = Callable[[dict[str, Any]], None]


def _create_run_directory() -> tuple[str, Path]:
    """Allocate a unique run directory even when jobs start in the same instant."""
    AGENT_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    for _ in range(4):
        run_id = f"agent-{timestamp}-{uuid.uuid4().hex}"
        run_dir = AGENT_RUNS_ROOT / run_id
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return run_id, run_dir
    raise FileExistsError("无法分配唯一的 Agent 运行目录")


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentCancelled("Agent 运行已取消。")


def _load_resume_source(run_id: str, *, tester_attempt: int | None = None) -> dict[str, Any]:
    """读取上一次运行的 Spec/Plan，用于从 Coder 继续执行。"""
    if tester_attempt is not None and (type(tester_attempt) is not int or tester_attempt < 1):
        raise ValueError("resume_tester_attempt 必须为正整数")
    name = str(run_id or "").strip()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("resume_from 必须是单个运行目录名")
    root = AGENT_RUNS_ROOT.resolve()
    source = (root / name).resolve()
    if root not in source.parents or not source.is_dir():
        raise FileNotFoundError(f"找不到要续跑的运行：{name}")
    # A controller may have rejected the latest tested candidate. Default
    # continuation must load the selected checkpoint, not that rejected input.
    result_path = source / 'result.json'
    if tester_attempt is None and result_path.is_file():
        result = json.loads(result_path.read_text(encoding='utf-8'))
        selected_report = result.get('selected_report') if isinstance(result, dict) else None
        if isinstance(selected_report, str) and result.get('passed') is False:
            for handoff in (source / 'handoffs').glob('tester_to_modifier_attempt*.json'):
                record = json.loads(handoff.read_text(encoding='utf-8'))
                if ((record.get('payload') or {}).get('artifacts') or {}).get('report') == selected_report:
                    selected_attempt = record.get('attempt')
                    if type(selected_attempt) is int and selected_attempt > 0:
                        return _load_resume_source(run_id, tester_attempt=selected_attempt)
            raise ValueError('保留的修复基线缺少对应 Tester handoff，拒绝恢复被回退的候选')
    artifacts = source / "artifacts"
    spec_path = artifacts / "effective_spec.md"
    if not spec_path.is_file():
        spec_path = artifacts / "spec.md"
    # A completed Coder handoff identifies the actual plan, including a
    # reference-plan substitution. Older/interrupted runs fall back to files.
    plan_path = artifacts / "plan_reference.json"
    if not plan_path.is_file():
        plan_path = artifacts / "plan.json"
    if not plan_path.is_file() and (artifacts / 'plan_draft.json').is_file():
        plan_path = artifacts / 'plan_draft.json'
    coder_handoff = source / "handoffs" / "coder_to_tester.json"
    if tester_attempt is None and coder_handoff.is_file():
        record = json.loads(coder_handoff.read_text(encoding="utf-8"))
        reference = ((record.get("payload") or {}).get("artifacts") or {}).get("plan")
        if isinstance(reference, str):
            candidate = (source / reference).resolve()
            if source.resolve() not in candidate.parents or not candidate.is_file():
                raise ValueError("上一次运行的 Plan 引用路径无效")
            plan_path = candidate
    if not spec_path.is_file() and tester_attempt is None:
        raise ValueError("上一次运行没有 Spec artifact，无法续跑")
    spec = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
    plan: dict[str, Any] | None = None
    if plan_path.is_file():
        loaded_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if isinstance(loaded_plan, dict) and isinstance(loaded_plan.get("modules"), list):
            plan = loaded_plan
    parser_result: dict[str, Any] = {}
    parser_path = artifacts / "parser_result.json"
    if parser_path.is_file():
        try:
            parsed = json.loads(parser_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                parser_result = parsed
        except json.JSONDecodeError:
            pass
    events_payload: dict[str, Any] = {}
    events_path = source / "events.json"
    if events_path.is_file():
        try:
            loaded = json.loads(events_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                events_payload = loaded
        except json.JSONDecodeError:
            pass
    source_events = events_payload.get("events") if isinstance(events_payload.get("events"), list) else []
    failed_event: dict[str, Any] | None = None
    if events_payload.get("status") == "passed" and tester_attempt is None:
        # A successful final Tester supersedes earlier failed repair attempts.
        # Re-test its exact input rather than jumping back into an older repair.
        failed_event = next((event for event in reversed(source_events)
                             if isinstance(event, dict) and event.get("node_id") == "tester"
                             and event.get("status") == "passed"), None)
        if failed_event is None:
            raise ValueError("已通过的运行缺少最终 Tester 事件，无法确定续跑快照")
    else:
        for event in reversed(source_events):
            if not isinstance(event, dict):
                continue
            if event.get("status") in {"failed", "cancelled", "running", "waiting_input"}:
                failed_event = event
                break
        if failed_event is None and source_events:
            failed_event = source_events[-1] if isinstance(source_events[-1], dict) else None
    stage = "modifier" if tester_attempt is not None else str((failed_event or {}).get("node_id") or "coder")
    if (tester_attempt is None and stage == 'reviewer'
            and str((failed_event or {}).get('title') or '').startswith('Protocol contract review')):
        stage = 'contract_review'
    if plan is None and stage not in {"parser", "planner"} and tester_attempt is None:
        raise ValueError("上一次运行没有 Plan artifact，无法从 Coder/Tester 续跑")
    title = str((failed_event or {}).get("title") or "")
    module_name = (failed_event or {}).get("module") if stage == "coder" else None
    if module_name is None and stage == "coder" and " · " in title:
        # Backward compatibility with runs created before structured identity.
        module_name = title.rsplit(" · ", 1)[-1]
    project_files: dict[str, str] = {}
    project_provenance: dict[str, dict[str, str]] = {}
    project_rtl = source / "project" / "rtl"
    if project_rtl.is_dir():
        for path in sorted(project_rtl.rglob("*.sv")):
            if source.resolve() not in path.resolve().parents:
                raise ValueError("上一次运行的 RTL 路径越出运行目录")
            project_files[path.relative_to(source / "project").as_posix()] = path.read_text(encoding="utf-8")
    # If an interrupted Modifier had already changed working files, restore
    # exactly the files used by its input Tester, from the handoff manifest.
    # Legacy manifests still point at project/rtl and retain old behavior.
    handoff_path: Path | None = None
    if tester_attempt is not None:
        handoff_path = source / "handoffs" / f"tester_to_modifier_attempt{tester_attempt}.json"
        if not handoff_path.is_file():
            raise ValueError(f"上一次运行没有第 {tester_attempt} 轮失败的 Tester → Modifier handoff")
    elif stage == "modifier":
        candidates = list((source / "handoffs").glob("tester_to_modifier_attempt*.json"))
        def attempt_number(path: Path) -> int:
            suffix = path.stem.rsplit("attempt", 1)[-1]
            return int(suffix) if suffix.isdigit() else -1
        if candidates:
            handoff_path = max(candidates, key=attempt_number)
    elif stage == "tester":
        attempt = (failed_event or {}).get("attempt", 1)
        if isinstance(attempt, int) and attempt > 1:
            handoff_path = source / "handoffs" / f"modifier_to_tester_attempt{attempt - 1}.json"
        else:
            handoff_path = coder_handoff
    if handoff_path and handoff_path.is_file():
        record = json.loads(handoff_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("上一次运行的 handoff 格式无效")
        handoff_artifacts = ((record.get("payload") or {}).get("artifacts") or {})
        if tester_attempt is not None:
            if (record.get("schema_version") != 1
                    or record.get("edge_id") != "tester_to_modifier"
                    or record.get("source") != "tester" or record.get("target") != "modifier"
                    or record.get("attempt") != tester_attempt
                    or (record.get("payload") or {}).get("attempt") != tester_attempt):
                raise ValueError("指定轮次的 Tester handoff 身份无效")
            if not all(isinstance(handoff_artifacts.get(key), str)
                       for key in ("spec", "plan", "rtl_manifest", "report")):
                raise ValueError("指定轮次的 Tester handoff 缺少必要 artifact")
            selected_spec_path = (source / handoff_artifacts["spec"]).resolve()
            if source.resolve() not in selected_spec_path.parents or not selected_spec_path.is_file():
                raise ValueError("指定轮次的 Spec 引用无效")
            spec = selected_spec_path.read_text(encoding="utf-8")
            selected_report_path = (source / handoff_artifacts["report"]).resolve()
            if source.resolve() not in selected_report_path.parents or not selected_report_path.is_file():
                raise ValueError("指定轮次的报告引用无效")
            selected_report = json.loads(selected_report_path.read_text(encoding="utf-8"))
            if not isinstance(selected_report, dict) or selected_report.get("passed") is not False:
                raise ValueError("只能从有失败报告的 Tester 轮次续跑")
        effective_plan_ref = handoff_artifacts.get("plan")
        if isinstance(effective_plan_ref, str):
            effective_plan_path = (source / effective_plan_ref).resolve()
            if source.resolve() not in effective_plan_path.parents or not effective_plan_path.is_file():
                raise ValueError("上一次运行的有效 Plan 引用无效")
            effective_plan = json.loads(effective_plan_path.read_text(encoding="utf-8"))
            if not isinstance(effective_plan, dict) or not isinstance(effective_plan.get("modules"), list):
                raise ValueError("上一次运行的有效 Plan 格式无效")
            plan = effective_plan
        manifest_ref = handoff_artifacts.get("rtl_manifest")
        if isinstance(manifest_ref, str):
            manifest_path = (source / manifest_ref).resolve()
            if source.resolve() not in manifest_path.parents or not manifest_path.is_file():
                raise ValueError("上一次运行的 RTL manifest 引用无效")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = manifest.get("files") if isinstance(manifest, dict) else None
            if not isinstance(entries, list) or not entries:
                raise ValueError("上一次运行的 RTL manifest 格式无效")
            project_files = {}
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("artifact"), str):
                    raise ValueError("上一次运行的 RTL manifest 文件引用无效")
                relative, reference = entry["path"], entry["artifact"]
                safe_project_path(source, relative)
                file_path = (source / reference).resolve()
                if source.resolve() not in file_path.parents or not file_path.is_file():
                    raise ValueError("上一次运行的 RTL 文件引用无效")
                if tester_attempt is not None:
                    snapshot_root = (source / "artifacts" / "rtl_snapshots").resolve()
                    digest = entry.get("sha256")
                    if (snapshot_root not in file_path.parents or not isinstance(digest, str)
                            or hashlib.sha256(file_path.read_bytes()).hexdigest() != digest):
                        raise ValueError("指定轮次缺少完整可信的不可变 RTL 快照，无法精确恢复")
                    if relative in project_files:
                        raise ValueError("指定轮次 RTL manifest 有重复文件路径")
                project_files[relative] = file_path.read_text(encoding="utf-8")
                project_provenance[relative] = {
                    key: entry[key] for key in ("implementation", "original_implementation")
                    if isinstance(entry.get(key), str)
                }
    if tester_attempt is not None:
        expected_files = {module.get("file") for module in (plan or {}).get("modules", [])
                          if isinstance(module, dict) and isinstance(module.get("file"), str)}
        if not expected_files or expected_files != set(project_files):
            raise ValueError("指定轮次 RTL 快照与有效计划的文件清单不一致")
    # Carry a prior evidence artifact even when interrupted at Tester (its
    # input is a Modifier handoff). It is revalidated against the current RTL
    # before use, so an old observation cannot masquerade as current evidence.
    diagnostic_evidence = None
    prior_tester_handoffs = sorted(
        [handoff_path] if tester_attempt is not None and handoff_path is not None
        else (source / "handoffs").glob("tester_to_*_attempt*.json"),
        key=lambda path: int(path.stem.rsplit("attempt", 1)[-1])
        if path.stem.rsplit("attempt", 1)[-1].isdigit() else -1,
        reverse=True,
    )
    for evidence_handoff in prior_tester_handoffs:
        record = json.loads(evidence_handoff.read_text(encoding="utf-8"))
        ref = ((record.get("payload") or {}).get("artifacts") or {}).get("diagnostic_evidence")
        if not isinstance(ref, str):
            continue
        path = (source / ref).resolve()
        if source.resolve() not in path.parents or not path.is_file():
            raise ValueError("上一次运行的诊断证据路径无效")
        if path.stat().st_size > 400_000:
            raise ValueError("上一次运行的诊断证据过大")
        diagnostic_evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(diagnostic_evidence, dict):
            raise ValueError("上一次运行的诊断证据格式无效")
        if tester_attempt is not None:
            matching_items, _ = _validated_evidence(diagnostic_evidence, project_files)
            diagnostic_evidence = ({"schema": "ai_eda.diagnostic_evidence.v1", "items": matching_items}
                                   if matching_items else None)
        break
    metadata_path = source / "metadata.json"
    metadata = {}
    if metadata_path.is_file():
        loaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if isinstance(loaded_metadata, dict):
            metadata = loaded_metadata
    source_project = metadata.get("project_id") or events_payload.get("project_id")
    source_mode = metadata.get("use_l1_reference")
    if not isinstance(source_mode, bool) and source_project == "rv32i5_cache":
        # Older records lack the mode field. A reference event proves that the
        # mode was enabled; no reference events cannot prove it was disabled.
        if any(
            event.get("node_id") == "coder"
            and (event.get("implementation") == "reference"
                 or "L1 reference" in str(event.get("response") or "")
                 or event.get("prompt") == "参考实现")
            for event in source_events if isinstance(event, dict)
        ):
            source_mode = True
    return {
        "run_id": name,
        "resume_tester_attempt": tester_attempt,
        "project_id": source_project,
        "use_l1_reference": source_mode,
        "diagnostic_evidence": diagnostic_evidence,
        "spec": spec,
        "plan": plan,
        "parser_result": parser_result,
        "source": source,
        "stage": stage,
        "module": module_name,
        "event": failed_event,
        "project_files": project_files,
        "project_provenance": project_provenance,
        "source_status": events_payload.get("status"),
    }


def _seed_modifier_input(
    context: RunContext,
    source: dict[str, Any],
    spec_ref: str,
    plan_ref: str,
    manifest_ref: str,
) -> Path:
    """为从 Modifier 失败点续跑重建 Tester → Modifier 输入。"""
    source_dir = source["source"]
    candidates = sorted(
        (source_dir / "handoffs").glob("tester_to_modifier_attempt*.json"),
        key=lambda path: int(path.stem.rsplit("attempt", 1)[-1])
        if path.stem.rsplit("attempt", 1)[-1].isdigit() else -1,
    )
    selected_attempt = source.get("resume_tester_attempt")
    if selected_attempt is not None:
        selected = source_dir / "handoffs" / f"tester_to_modifier_attempt{selected_attempt}.json"
        candidates = [selected] if selected.is_file() else []
    if not candidates:
        raise ValueError("上一次运行没有 Tester → Modifier handoff，无法从 Modifier 续跑")
    record = json.loads(candidates[-1].read_text(encoding="utf-8"))
    payload = record.get("payload") if isinstance(record, dict) else None
    artifacts = (payload or {}).get("artifacts") or {}
    source_report_ref = artifacts.get("report")
    if not isinstance(source_report_ref, str):
        raise ValueError("上一次运行缺少失败报告，无法从 Modifier 续跑")
    source_report = (source_dir / source_report_ref).resolve()
    if source_dir.resolve() not in source_report.parents or not source_report.is_file():
        raise ValueError("上一次运行的失败报告路径无效")
    report = json.loads(source_report.read_text(encoding="utf-8"))
    report_ref = context.write_json_artifact("resume_report.json", report)
    evidence_ref = context.options.get("diagnostic_evidence_ref")
    if not evidence_ref and selected_attempt is None and isinstance(artifacts.get("diagnostic_evidence"), str):
        source_evidence = (source_dir / artifacts["diagnostic_evidence"]).resolve()
        if source_dir.resolve() not in source_evidence.parents or not source_evidence.is_file():
            raise ValueError("上一次运行的诊断证据路径无效")
        evidence = json.loads(source_evidence.read_text(encoding="utf-8"))
        evidence_ref = context.write_json_artifact("diagnostic_evidence_resume.json", evidence)
        context.options["diagnostic_evidence_ref"] = evidence_ref
    return context.write_handoff(
        "tester",
        "modifier",
        {
            "attempt": 1,
            **({"source_tester_attempt": selected_attempt} if selected_attempt is not None else {}),
            "summary": (payload or {}).get("summary") or "上一轮 Tester 失败",
            "artifacts": {
                "spec": spec_ref,
                "plan": plan_ref,
                "rtl_manifest": manifest_ref,
                "report": report_ref,
                **({"diagnostic_evidence": evidence_ref} if evidence_ref else {}),
            },
        },
        attempt=1,
        label=f"Resume {source['run_id']}: continue from Modifier",
    )


def _copy_resume_files(context: RunContext, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = safe_project_path(context.run_dir, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _seed_resume_project(
    context: RunContext,
    source: dict[str, Any],
    spec_ref: str,
    plan_ref: str,
) -> dict[str, Any]:
    """把上次项目的 RTL 复制到新运行，并建立进入 Tester 的 manifest/handoff。"""
    files = source.get("project_files") or {}
    if not isinstance(files, dict) or not files:
        raise ValueError("上一次运行没有可续跑的 RTL 项目文件")
    _copy_resume_files(context, files)
    manifest = context.snapshot_rtl_manifest(files, "resume")
    provenance = source.get("project_provenance") or {}
    for entry in manifest["files"]:
        entry.update(provenance.get(entry["path"], {}))
    manifest_ref = context.write_json_artifact("rtl_manifest_resume.json", manifest)
    tester_input = context.write_handoff(
        "coder",
        "tester",
        {
            "artifacts": {
                "spec": spec_ref,
                "plan": plan_ref,
                "rtl_manifest": manifest_ref,
            }
        },
        label=f"Resume {source['run_id']}: reuse current RTL",
    )
    return {"handler": tester_input, "files": files, "manifest": manifest_ref}


def _carry_modifier_memory(
    modifier: ModifierAgent, resume_source: dict[str, Any] | None
) -> None:
    """把上游运行的紧凑修复记忆带进新运行。

    续跑时 Modifier 的对话上下文是空的，模型会重复上一轮已经失败的补丁。
    这里只搬运"上轮诊断 / 失败指纹 / 失败测试名"三个小字段（不含整段对话），
    让 Modifier 的 prompt 能识别"同一失败换了个说法"和"上次这么改没用"。
    """
    if not resume_source:
        return
    source = resume_source.get("source")
    if source is None:
        return
    path = Path(source) / "agents" / "modifier" / "context.json"
    if not path.is_file():
        return
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(old, dict):
        return
    carry = {
        key: old[key]
        for key in ("notes", "failure_fingerprint", "failing_tests", "recent_repair_trials")
        if key in old
    }
    if carry:
        modifier.save_context(**carry)
    evaluation_ref = old.get('last_repair_evaluation_ref')
    if isinstance(evaluation_ref, str):
        evaluation_path = (Path(source) / evaluation_ref).resolve()
        if Path(source).resolve() in evaluation_path.parents and evaluation_path.is_file():
            try:
                evaluation = json.loads(evaluation_path.read_text(encoding='utf-8'))
            except (OSError,json.JSONDecodeError):
                evaluation = None
            if isinstance(evaluation,dict):
                evaluation['source_run'] = resume_source.get('run_id')
                copied = modifier.runtime.write_json_artifact('resume_repair_evaluation.json', evaluation)
                modifier.save_context(last_repair_evaluation_ref=copied)


def run_agent(
    *,
    thinking: bool = True,
    reasoning_effort: str = "low",
    temperature: float = 0.2,
    max_tokens: int = 60000,
    max_calls: int = 100,
    max_repair_attempts: int = 8,
    planner_skill: bool = False,
    use_l1_reference: bool = True,
    diagnostic_evidence: dict[str, Any] | None = None,
    resume_from: str | None = None,
    resume_tester_attempt: int | None = None,
    resume_retest_checkpoint: bool = False,
    on_event: EventSink | None = None,
    cancel_event: Any = None,
    design_id: str | None = None,
    design_name: str | None = None,
    project_id: str | None = None,
    request_input: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """运行固定流水线：Parser → Planner → Coder → Tester ⇄ Modifier。

    ``graph.json`` 只是该固定流程的只读可视化，不参与调度。每个 Agent 都从上游
    handoff 中取得 artifact 引用，再按引用读取 Spec、RTL 或报告内容。
    """
    graph = load_agent_graph()
    if reasoning_effort not in {"low", "high", "max"}:
        raise ValueError("reasoning_effort 无效")
    if not 1 <= int(max_calls) <= 1000:
        raise ValueError("max_calls 必须在 1 到 1000 之间")
    if not 1 <= int(max_repair_attempts) <= 10:
        raise ValueError("max_repair_attempts 必须在 1 到 10 之间")
    # Each model repair may receive at most two local, model-free ablations.
    max_verifications = 1 + 3 * int(max_repair_attempts)
    if not isinstance(resume_retest_checkpoint, bool):
        raise ValueError("resume_retest_checkpoint 必须是布尔值")
    if resume_retest_checkpoint and resume_tester_attempt is None:
        raise ValueError("重新测试历史快照需要指定 Tester 轮次")
    if resume_tester_attempt is not None and not resume_from:
        raise ValueError("resume_tester_attempt 必须与 resume_from 同时提供")
    if resume_tester_attempt is not None:
        resume_source = _load_resume_source(resume_from, tester_attempt=resume_tester_attempt)
    else:
        resume_source = _load_resume_source(resume_from) if resume_from else None
    source_project = (resume_source or {}).get("project_id")
    project = get_project(project_id or source_project)
    if source_project and project["id"] != source_project:
        raise ValueError(f"续跑项目不匹配：原运行是 {source_project}，请求为 {project['id']}")
    source_reference_mode = (resume_source or {}).get("use_l1_reference")
    if isinstance(source_reference_mode, bool) and source_reference_mode != bool(use_l1_reference):
        raise ValueError("续跑必须使用与原运行一致的 L1 参考实现设置")
    spec_base = agent_task_spec(project["id"])
    run_id, run_dir = _create_run_directory()
    _write_json(run_dir / "graph.json", graph)
    (run_dir / "project").mkdir(exist_ok=True)

    events: list[dict[str, Any]] = []
    started_at = _now()
    started_clock = time.perf_counter()
    current_status = "running"
    final_report: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    effective_spec = spec_base
    parser_result: dict[str, Any] = {}
    plan: dict[str, Any] | None = None
    files: list[dict[str, Any]] = []
    tester_attempts = 0
    modification_rounds = 0
    verification_count = 0

    def persist(status: str = "running", error: str | None = None) -> None:
        _write_json(
            run_dir / "events.json",
            _run_payload(
                run_id=run_id,
                run_dir=run_dir,
                graph=graph,
                events=events,
                status=status,
                started_at=started_at,
                report=final_report,
                result=final_result,
                spec=effective_spec,
                error=error,
                design_id=design_id,
                design_name=design_name,
                project_id=project["id"],
                resumed_from=resume_from,
            ),
        )

    def emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(json.loads(json.dumps(event, ensure_ascii=False)))

    def begin_event(
        node_id: str, node_type: str, title: str, prompt: str, attempt: int = 1
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "run_id": run_id,
            "step": len(events) + 1,
            "node_id": node_id,
            "node_type": node_type,
            "title": title,
            "prompt": prompt,
            "status": "running",
            "attempt": attempt,
            "started_at": _now(),
            "_started_clock": time.perf_counter(),
        }
        events.append(event)
        persist()
        emit(event)
        return event

    def finish_event(event: dict[str, Any], status: str, **fields: Any) -> None:
        event.update(fields)
        event["status"] = status
        event["duration_ms"] = round(
            (time.perf_counter() - event.get("_started_clock", time.perf_counter())) * 1000
        )
        event.pop("_started_clock", None)
        event["finished_at"] = _now()
        persist()
        emit(event)

    def check_cancel() -> None:
        _check_cancel(cancel_event)

    persist()
    try:
        context = RunContext(
            run_dir=run_dir,
            options={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thinking": thinking,
                "reasoning_effort": reasoning_effort,
                "planner_skill": bool(planner_skill),
                "use_l1_reference": bool(use_l1_reference),
                "project": project,
            },
            begin_event=begin_event,
            finish_event=finish_event,
            persist=persist,
            emit=emit,
            check_cancel=check_cancel,
            request_input=request_input,
            max_calls=max_calls,
        )
        if diagnostic_evidence is None and resume_source:
            diagnostic_evidence = resume_source.get("diagnostic_evidence")
        if diagnostic_evidence is not None:
            if not isinstance(diagnostic_evidence, dict):
                raise ValueError("诊断证据必须是 JSON 对象")
            encoded_evidence = json.dumps(diagnostic_evidence, ensure_ascii=False)
            if len(encoded_evidence) > 100_000:
                raise ValueError("诊断证据超过 100000 字符")
            context.options["diagnostic_evidence_ref"] = context.write_json_artifact(
                "diagnostic_evidence.json", diagnostic_evidence
            )
        if resume_source:
            effective_spec = resume_source["spec"]
            plan = resume_source["plan"]
            parser_result = resume_source.get("parser_result") or {}
            resume_stage = "tester" if resume_retest_checkpoint else str(resume_source.get("stage") or "coder")
            if resume_stage == "modifier":
                # 续跑从 Modifier 输入开始；随后第一次 Tester 应使用第 2 轮，
                # 避免与 seed 的 tester_to_modifier_attempt1.json 重名。
                tester_attempts = 1
            spec_ref = context.write_text_artifact("effective_spec.md", effective_spec)
            plan_ref = context.write_json_artifact("plan.json", plan)
            parser_result_ref = context.write_json_artifact(
                "parser_result_resume.json", parser_result
            )
            if resume_stage == "parser":
                initial_handoff = context.write_handoff(
                    "spec",
                    "parser",
                    {"task": project["id"], "artifacts": {"spec": context.write_text_artifact("spec.md", effective_spec)}},
                    label=f"Resume {resume_from}: continue from Parser",
                )
                parser = ParserAgent(context)
                parser_handoff = parser.run(initial_handoff)
                planner = PlannerAgent(context)
                planner_handoff = planner.run(parser_handoff)
                coder = CoderAgent(context)
                next_tester_input = coder.run(planner_handoff)
            elif resume_stage == 'contract_review':
                planner = PlannerAgent(context)
                context.write_json_artifact('plan_draft.json', plan)
                reviewed_plan = planner._review_protocol(effective_spec, plan)
                reviewed_ref = context.write_json_artifact('plan_reviewed.json', reviewed_plan)
                planner_handoff = context.write_handoff('planner','coder',{'artifacts':{
                    'spec':spec_ref,'plan':reviewed_ref,'parser_result':parser_result_ref}},
                    label='Resume contract review: retain original model draft, then generate RTL')
                next_tester_input = CoderAgent(context).run(planner_handoff)
            elif resume_stage == "planner":
                parser_result_ref = context.write_json_artifact(
                    "parser_result_resume.json", parser_result
                )
                parser_handoff = context.write_handoff(
                    "parser",
                    "planner",
                    {
                        "artifacts": {
                            "spec": spec_ref,
                            "parser_result": parser_result_ref,
                        }
                    },
                    label=f"Resume {resume_from}: continue from Planner",
                )
                planner = PlannerAgent(context)
                planner_handoff = planner.run(parser_handoff)
                coder = CoderAgent(context)
                next_tester_input = coder.run(planner_handoff)
            elif resume_stage == "coder":
                _copy_resume_files(context, resume_source.get("project_files") or {})
                planner_handoff = context.write_handoff(
                    "planner",
                    "coder",
                    {
                        "artifacts": {
                            "spec": spec_ref,
                            "plan": plan_ref,
                            "parser_result": parser_result_ref,
                        }
                    },
                    label=f"Resume {resume_from}: continue from Coder",
                )
                coder = CoderAgent(context)
                next_tester_input = coder.run(
                    planner_handoff,
                    existing_files=resume_source.get("project_files") or {},
                    start_module=resume_source.get("module"),
                )
            elif resume_stage in {"tester", "modifier", "summary"}:
                seeded = _seed_resume_project(
                    context, resume_source, spec_ref, plan_ref
                )
                if resume_stage == "modifier":
                    modifier_input = _seed_modifier_input(
                        context,
                        resume_source,
                        spec_ref,
                        plan_ref,
                        seeded["manifest"],
                    )
                    modifier = ModifierAgent(context)
                    # Continue with a compact diagnosis, not the potentially huge
                    # old conversation or stale artifact references. This lets the
                    # agent recognize a repeated failure after a resumed run.
                    old_context_path = resume_source["source"] / "agents" / "modifier" / "context.json"
                    if resume_tester_attempt is None and old_context_path.is_file():
                        try:
                            old_context = json.loads(old_context_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            old_context = {}
                        if isinstance(old_context, dict):
                            carry = {key: old_context[key] for key in ("notes", "failure_fingerprint", "failing_tests", "recent_repair_trials")
                                     if key in old_context}
                            if carry:
                                modifier.save_context(**carry)
                    next_tester_input = modifier.run(modifier_input, 1)
                    modification_rounds = 1
                else:
                    # 已有完整 RTL 时直接从 Tester 继续。
                    next_tester_input = seeded["handler"]
            else:
                raise ValueError(
                    f"上一次运行停在 {resume_stage}，没有可直接继续的 Coder/Tester 产物"
                )
        else:
            resume_stage = None
            spec_ref = context.write_text_artifact("spec.md", spec_base)
            initial_handoff = context.write_handoff(
                "spec",
                "parser",
                {"task": project["id"], "artifacts": {"spec": spec_ref}},
                label="Input Spec → Parser: Spec artifact",
            )

            parser = ParserAgent(context)
            parser_handoff = parser.run(initial_handoff)

            planner = PlannerAgent(context)
            planner_handoff = planner.run(parser_handoff)
            coder = CoderAgent(context)
            next_tester_input = coder.run(planner_handoff)

        tester = TesterAgent(context)
        modifier = ModifierAgent(context)
        _carry_modifier_memory(modifier, resume_source if resume_from else None)
        retained_handoff = None
        retained_report = None
        consecutive_rejections = 0
        repair_stop_reason = None
        pending_ablations = []
        while True:
            tester_attempts += 1
            verification_count += 1
            tested_payload = context.read_handoff(next_tester_input)['payload']
            tester_handoff = tester.run(next_tester_input, tester_attempts)
            tester_payload = context.read_handoff(tester_handoff)["payload"]
            tester_artifacts = tester_payload.get("artifacts") or {}
            report_ref = tester_artifacts.get("report")
            if not isinstance(report_ref, str):
                raise ValueError("Tester handoff 缺少报告 artifact")
            report = context.read_json_artifact(report_ref)
            if not isinstance(report, dict):
                raise ValueError("Tester 报告 artifact 格式无效")
            final_report = report
            if retained_report is not None:
                evaluation = evaluate_repair(retained_report, report)
                evaluation.update(candidate_report=report_ref,
                                  baseline_handoff=context.artifact_ref(retained_handoff),
                                  candidate_paths=tested_payload.get('changed_paths') or [],
                                  candidate_ablation=bool(tested_payload.get('candidate_ablation')))
                evaluation_ref = context.write_json_artifact(
                    f'repair_evaluation_attempt{tester_attempts}.json', evaluation)
                modifier.save_context(last_repair_evaluation_ref=evaluation_ref)
                trials=list(modifier.context.get('recent_repair_trials') or [])
                trials.append({'source_run':run_id,'candidate_report':report_ref,
                    'paths':evaluation['candidate_paths'],'ablation':evaluation['candidate_ablation'],
                    'accepted':evaluation['accepted'],'reasons':evaluation['reasons']})
                modifier.save_context(recent_repair_trials=trials[-4:])
                if not evaluation['accepted']:
                    # Restore only immutable, previously model-generated files.
                    # Keep all rejected candidate reports and manifests intact.
                    pending_ablations.extend(build_file_ablations(context, retained_handoff,
                        next_tester_input, tester_attempts, limit=max_verifications-verification_count))
                    tester_handoff = retained_handoff
                    final_report = retained_report
                    if not tested_payload.get('candidate_ablation'):
                        consecutive_rejections += 1
                else:
                    retained_handoff, retained_report = tester_handoff, report
                    consecutive_rejections = 0
            else:
                retained_handoff, retained_report = tester_handoff, report
            restore_checkpoint(context, retained_handoff)
            if report.get("passed"):
                break
            if verification_count >= max_verifications:
                break
            if pending_ablations:
                next_tester_input = pending_ablations.pop(0)
                continue
            if consecutive_rejections >= 2:
                repair_stop_reason = 'Two consecutive candidates brought no verified improvement; retained baseline for a new diagnosis.'
                break
            if modification_rounds >= int(max_repair_attempts):
                break
            if context.max_calls > 0 and context.model_calls >= context.max_calls:
                repair_stop_reason = 'Model-call budget exhausted; retained the selected tested checkpoint.'
                break
            check_cancel()
            try:
                modification_rounds += 1
                next_tester_input = modifier.run(tester_handoff, tester_attempts)
            except (ModelCallBudgetExceeded,InvalidModelRepair) as error:
                repair_stop_reason = str(error) + ' Retained the selected tested checkpoint.'
                for pending in events:
                    if pending.get('status') == 'running':
                        finish_event(pending, 'failed', error=repair_stop_reason, streaming=False)
                break

        if final_report is None:
            raise ValueError("Tester 没有产出验收报告")
        final_handoff = context.read_handoff(tester_handoff)["payload"]
        final_artifacts = final_handoff.get("artifacts") or {}
        spec_ref = final_artifacts.get("spec")
        plan_ref = final_artifacts.get("plan")
        manifest_ref = final_artifacts.get("rtl_manifest")
        if not all(isinstance(ref, str) for ref in (spec_ref, plan_ref, manifest_ref)):
            raise ValueError("最终 handoff 缺少 Spec、Plan 或 RTL manifest artifact")
        effective_spec = context.read_text_artifact(spec_ref)
        plan = context.read_json_artifact(plan_ref)
        manifest = context.read_json_artifact(manifest_ref)
        if not isinstance(plan, dict) or not isinstance(manifest, dict):
            raise ValueError("最终 artifact 格式无效")
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        if not resume_from:
            parser_payload = context.read_handoff(parser_handoff)["payload"]
            parser_result_ref = (parser_payload.get("artifacts") or {}).get("parser_result")
            if isinstance(parser_result_ref, str):
                parsed = context.read_json_artifact(parser_result_ref)
                parser_result = parsed if isinstance(parsed, dict) else {}
        passed = bool(final_report.get("passed"))
        final_result = {
            "passed": passed,
            "stage": final_report.get("stage"),
            "summary": _report_summary(final_report),
            "metrics": final_report.get("metrics") or {},
            "spec": effective_spec,
            "plan": plan,
            "files": files,
            "parser_rounds": parser_result.get("rounds", 1),
            "supplements": parser_result.get("supplements", []),
            "tester_attempts": tester_attempts,
            "modifier_attempts": modification_rounds,
            "verification_attempts": verification_count,
            "repair_stop_reason": repair_stop_reason,
            "selected_report": (context.read_handoff(tester_handoff)['payload'].get('artifacts') or {}).get('report'),
            "resumed_from": resume_from,
            "resume_tester_attempt": resume_tester_attempt,
            "resume_retest_checkpoint": resume_retest_checkpoint,
            "use_l1_reference": bool(use_l1_reference),
            "cpu_capability": final_report.get("cpu_capability"),
            "test_suites": final_report.get("test_suites"),
            "performance": final_report.get("performance"),
        }
        _write_json(run_dir / "result.json", final_result)
        current_status = "passed" if passed else "failed"
    except AgentCancelled as error:
        current_status = "cancelled"
        for pending in events:
            if pending.get("status") in {"running", "waiting_input"}:
                pending.update(
                    {"status": "cancelled", "finished_at": _now(), "error": str(error)}
                )
        payload = _run_payload(
            run_id=run_id,
            run_dir=run_dir,
            graph=graph,
            events=events,
            status=current_status,
            started_at=started_at,
            finished_at=_now(),
            report=final_report,
            result=final_result,
            spec=effective_spec,
            resumed_from=resume_from,
            error=str(error),
            design_id=design_id,
            design_name=design_name,
            project_id=project["id"],
        )
        payload["duration_ms"] = round((time.perf_counter() - started_clock) * 1000)
        _write_json(run_dir / "events.json", payload)
        try:
            _write_metadata(
                run_dir,
                graph=graph,
                run_id=run_id,
                status=current_status,
                started_at=started_at,
                finished_at=payload["finished_at"],
                attempts=tester_attempts or 1,
                max_repair_attempts=max_repair_attempts,
                use_l1_reference=bool(use_l1_reference),
                resumed_from=resume_from,
                resume_tester_attempt=resume_tester_attempt,
                resume_retest_checkpoint=resume_retest_checkpoint,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                design_id=design_id,
                design_name=design_name,
                project_id=project["id"],
            )
        except Exception:
            pass
        raise
    except Exception as error:
        current_status = "failed"
        for pending in events:
            if pending.get("status") in {"running", "waiting_input"}:
                pending.update(
                    {"status": "failed", "finished_at": _now(), "error": str(error)}
                )
        payload = _run_payload(
            run_id=run_id,
            run_dir=run_dir,
            graph=graph,
            events=events,
            status=current_status,
            started_at=started_at,
            finished_at=_now(),
            report=final_report,
            result=final_result,
            spec=effective_spec,
            resumed_from=resume_from,
            error=str(error),
            design_id=design_id,
            design_name=design_name,
            project_id=project["id"],
        )
        payload["duration_ms"] = round((time.perf_counter() - started_clock) * 1000)
        _write_json(run_dir / "events.json", payload)
        try:
            _write_metadata(
                run_dir,
                graph=graph,
                run_id=run_id,
                status=current_status,
                started_at=started_at,
                finished_at=payload["finished_at"],
                attempts=tester_attempts or 1,
                max_repair_attempts=max_repair_attempts,
                use_l1_reference=bool(use_l1_reference),
                resumed_from=resume_from,
                resume_tester_attempt=resume_tester_attempt,
                resume_retest_checkpoint=resume_retest_checkpoint,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                design_id=design_id,
                design_name=design_name,
                project_id=project["id"],
            )
        except Exception:
            pass
        raise

    payload = _run_payload(
        run_id=run_id,
        run_dir=run_dir,
        graph=graph,
        events=events,
        status=current_status,
        started_at=started_at,
        finished_at=_now(),
        report=final_report,
        result=final_result,
        spec=effective_spec,
        resumed_from=resume_from,
        design_id=design_id,
        design_name=design_name,
        project_id=project["id"],
    )
    payload["duration_ms"] = round((time.perf_counter() - started_clock) * 1000)
    _write_json(run_dir / "events.json", payload)
    _write_metadata(
        run_dir,
        graph=graph,
        run_id=run_id,
        status=current_status,
        started_at=started_at,
        finished_at=payload["finished_at"],
        attempts=tester_attempts or 1,
        max_repair_attempts=max_repair_attempts,
        use_l1_reference=bool(use_l1_reference),
        resumed_from=resume_from,
        resume_tester_attempt=resume_tester_attempt,
        resume_retest_checkpoint=resume_retest_checkpoint,
        temperature=temperature,
        max_tokens=max_tokens,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        design_id=design_id,
        design_name=design_name,
        project_id=project["id"],
    )
    return payload



