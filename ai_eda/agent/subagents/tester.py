"""Tester 子 Agent：编译项目、运行教师 TB、评估面积 / 功耗。"""

from __future__ import annotations

from pathlib import Path

from ai_eda.agent.projects import get_project
from ai_eda.agent.skills.l1_icache_probe import add_l1_icache_probe_to_report, run_l1_icache_flush_probe
from ai_eda.agent.skills.l1_id_hazard_probe import add_l1_id_hazard_to_report, run_l1_id_hazard_probe
from ai_eda.agent.skills.rtl_structure import inspect_rtl_structure
from ai_eda.agent.skills.retirement_observer import observe_retirement
from ai_eda.agent.skills.retire_tail import capture_retire_tail
from ai_eda.agent.skills.data_bus_observer import observe_data_bus
from ai_eda.agent.skills.signal_probe import run_signal_probe
from ai_eda.agent.repair_focus import make_repair_ticket
from ai_eda.rtl.runner import save_report, test_rtl

from .base import SubAgent
from .common import combine_files, report_feedback, report_summary


def answer_observation_request(runtime, *, files: dict, report: dict, request: dict, attempt: int, request_index: int=1) -> dict:
    """Tester answers a bounded Modifier question using the current snapshot."""
    import hashlib
    suffix='' if request_index==1 else f'_retry{request_index}'
    snapshot = runtime.write_text_artifact(f'observation_snapshot_attempt{attempt}{suffix}.sv', combine_files(files))
    allowed = {str(c.get('testcase') or c.get('test') or c.get('name') or '')
               for c in report.get('checks') or [] if isinstance(c, dict)}
    if isinstance(report.get('repair_ticket'),dict):
        allowed.add(report['repair_ticket']['testcase'])
    request_ref = runtime.write_json_artifact(f'observation_request_attempt{attempt}{suffix}.json', {
        'source': 'modifier', 'request': request,
        'file_hashes': {path: hashlib.sha256(text.encode()).hexdigest() for path, text in files.items()}})
    runtime.check_cancel()
    observation = run_signal_probe(project=runtime.options.get('project') or {},
        combined_path=runtime.run_dir / snapshot, output_dir=runtime.run_dir / f'modifier-probe-{attempt:02d}{suffix}',
        plan=request, allowed_tests=allowed)
    runtime.check_cancel()
    runtime.write_json_artifact(f'observation_answer_attempt{attempt}{suffix}.json',
        {'source': 'tester', 'request_ref': request_ref, 'observation': observation})
    return observation



class TesterAgent(SubAgent):
    name = "tester"
    title = "04 · Tester"
    node_type = "tester"

    def run(self, input_handoff: Path, attempt: int) -> Path:
        incoming = self.runtime.read_handoff(input_handoff)["payload"]
        artifacts = incoming.get("artifacts") or {}
        spec_ref = artifacts.get("spec")
        plan_ref = artifacts.get("plan")
        manifest_ref = artifacts.get("rtl_manifest")
        if not all(isinstance(ref, str) for ref in (spec_ref, plan_ref, manifest_ref)):
            raise ValueError("Tester 输入缺少 Spec、Plan 或 RTL manifest artifact")
        plan = self.runtime.read_json_artifact(plan_ref)
        manifest = self.runtime.read_json_artifact(manifest_ref)
        if not isinstance(plan, dict):
            raise ValueError("Plan artifact 格式无效")
        entries = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError("RTL manifest 格式无效")
        files: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("artifact"), str):
                raise ValueError("RTL manifest 含有无效文件引用")
            files[entry["path"]] = self.runtime.read_text_artifact(entry["artifact"])
        combined_ref = self.runtime.write_text_artifact(
            f"generated_attempt{attempt}.sv", combine_files(files)
        )
        combined_path = self.runtime.run_dir / combined_ref
        tester_dir = self.runtime.run_dir / f"tester-{attempt:02d}"
        tester_dir.mkdir(exist_ok=True)
        prompt = (
            f"Round {attempt}: compile {len(files)} project files and run the fixed teacher TB; "
            "generate power activity and synthesized area as well."
        )
        event = self.runtime.begin_event(
            "tester", self.node_type, f"{self.title} · Round {attempt}", prompt, attempt
        )
        project = self.runtime.options.get("project") or get_project()
        report = test_rtl(
            task_name=project["task_name"],
            testbench_path=project["testbench_path"],
            testbench_top=project["testbench_top"],
            rtl_path=combined_path,
            power_testbench_path=project["power_testbench_path"],
            power_testbench_top=project["power_testbench_top"],
            expected_cpu_level=project.get("expected_cpu_level"),
            rtl_top_module=plan.get("top_module"),
            timeout_seconds=int(project.get("timeout_seconds", 20)),
            run_dir=tester_dir,
        )
        self.check_cancel()
        report['teacher_checks'] = [dict(c) for c in report.get('checks') or [] if isinstance(c,dict)]
        if report.get('stage') == 'simulation' and not report.get('passed'):
            report['data_bus_observation'] = observe_data_bus(
                project=project, combined_path=combined_path, output_dir=tester_dir / 'data_bus_observer')
            self.check_cancel()
            report['structural_diagnostics'] = inspect_rtl_structure(
                combined_path, plan.get('top_module'), tester_dir / 'structure')
            if project.get('testbench_top') == 'tb_agent_rv32i5':
                report['retirement_observation'] = observe_retirement(
                    project=project, combined_path=combined_path, output_dir=tester_dir / 'retirement_observer')
            # A halt timeout hides the loop body: record the last retirements so the
            # Modifier can see which PCs repeat instead of only a frozen imem_addr.
            if any('等待 halted 超时' in str(check.get('detail') or '')
                   for check in report.get('checks') or [] if isinstance(check, dict)):
                report['retire_tail'] = capture_retire_tail(
                    project=project, combined_path=combined_path, output_dir=tester_dir / 'retire_tail')
            self.check_cancel()
        if project.get("id") == "rv32i5_cache" and report.get("stage") == "simulation":
            probe = run_l1_icache_flush_probe(
                plan=plan, files=files, combined_path=combined_path,
                output_dir=tester_dir / "l1_icache_flush_edge",
                timeout_seconds=int(project.get("timeout_seconds", 20)),
            )
            add_l1_icache_probe_to_report(report, probe)
            control_probe = run_l1_id_hazard_probe(
                plan=plan, files=files, combined_path=combined_path,
                output_dir=tester_dir / "l1_id_hazard",
                timeout_seconds=int(project.get("timeout_seconds", 20)),
            )
            # Do not let a repair evade a previously applicable verification
            # by changing its topology so the checker no longer recognizes it.
            control_required = bool(self.context.get("id_hazard_required"))
            add_l1_id_hazard_to_report(report, control_probe, required=control_required)
            if control_probe.get("status") not in {"not_covered", "error"}:
                self.save_context(id_hazard_required=True)
        self.check_cancel()
        if not report.get('passed'):
            report['repair_ticket'] = make_repair_ticket(report)
        report_path = save_report(tester_dir, report)
        self.save_context(
            attempts=int(self.context.get("attempts", 0)) + 1,
            plan_ref=plan_ref,
            rtl_manifest_ref=manifest_ref,
        )
        report_ref = self.runtime.artifact_ref(report_path)
        self.finish(
            event,
            "passed" if report.get("passed") else "failed",
            response=report_summary(report),
            report=report,
            feedback=report_feedback(report),
        )
        target = "summary" if report.get("passed") else "modifier"
        label = "Tester → Summary: final report artifact" if report.get("passed") else "Tester → Modifier: failure report artifact"
        return self.runtime.write_handoff(
            "tester",
            target,
            {
                "attempt": attempt,
                "summary": report_summary(report),
                "artifacts": {
                    "spec": spec_ref,
                    "plan": plan_ref,
                    "rtl_manifest": manifest_ref,
                    "report": report_ref,
                    "combined_rtl": combined_ref,
                    **({"diagnostic_evidence": self.runtime.options["diagnostic_evidence_ref"]}
                       if isinstance(self.runtime.options.get("diagnostic_evidence_ref"), str) else {}),
                },
            },
            attempt=attempt,
            label=label,
        )
