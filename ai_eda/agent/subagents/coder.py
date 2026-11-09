"""Coder 子 Agent：按计划逐文件生成 RTL。"""

from __future__ import annotations

import json
from pathlib import Path

from ai_eda.model.client import RTL_SYSTEM_PROMPT
from ai_eda.rtl.runner import extract_rtl
from ai_eda.agent.skills.rv32i5_l1_reference import build_reference_plan, load_reference
from ai_eda.agent.skills.rv32i5_contract import coder_context
from ai_eda.agent.rtl_contracts import extract_module_header

from .base import SubAgent
from .common import RV32I_L1_CODE_PATTERNS, RV32I_PIPELINE_CHECKLIST, safe_project_path, extract_json_payload, validate_modifier_files


def _architecture_block(plan: dict) -> str:
    architecture = plan.get("architecture")
    if not isinstance(architecture, dict):
        return ""
    parameters = architecture.get("parameters") or {}
    directives = architecture.get("coder_directives") or []
    reference = architecture.get("reference_structure") or {}
    return (
        "\n\nPlanner Skill 预评估架构参数（直接来自 Python Skill，必须严格遵守）：\n"
        + json.dumps(parameters, ensure_ascii=False, indent=2)
        + "\n\nCoder 指令：\n"
        + "\n".join(f"- {item}" for item in directives)
        + "\n\n参考结构：\n"
        + json.dumps(reference, ensure_ascii=False, indent=2)
        + "\n"
    )


class CoderAgent(SubAgent):
    name = "coder"
    title = "03 · Coder"
    node_type = "coder"
    # RTL 生成同样属于工具型输出。L1/L2 的 Plan+Spec 很长，思考模式可能把
    # 60k 输出预算全部消耗在 reasoning 上，导致没有 RTL 文本。默认关闭思考，
    # 把预算留给完整的 SystemVerilog 文件。
    MODEL_OPTIONS = {"thinking": False}

    def _coordinated_files(self, spec: str, plan: dict, checklist: str) -> dict[str, str]:
        prompt = (
            '在同一次实现中联合生成整个 RTL 工程，让所有模块共享同一套时序、控制编码和请求状态。'
            '所有计划文件必须完整返回，每文件只包含其计划模块；禁止遗漏辅助模块或使用占位实现。'
            '严格遵循冻结的端口合同、架构和规格；跨模块逐拍推演接受、响应、hold、bubble、flush、'
            '前递和退休，确保一条指令的 PC/指令/数据在整条路径中对应。'
            '只返回 JSON：{"files":[{"path":"rtl/module.sv","content":"完整 RTL"}]}。'
            '\n\nPlan:\n' + json.dumps(plan, ensure_ascii=False) + '\n\nSpec:\n' + spec + checklist
        )
        event = self.runtime.begin_event('coder', self.node_type, self.title + ' · coordinated project', prompt)
        event.update(implementation='model', generation_mode='coordinated')
        messages = [{'role': 'system', 'content': RTL_SYSTEM_PROMPT + '\nReturn the complete project as the requested JSON files object.'},
                    {'role': 'user', 'content': prompt}]
        for attempt in range(2):
            result = self.runtime.call_model_messages(event, messages, model_options=self.MODEL_OPTIONS)
            answer = result.get('answer') or ''
            try:
                files = validate_modifier_files(extract_json_payload(answer), plan)
                expected = {module['file'] for module in plan['modules']}
                if set(files) != expected:
                    raise ValueError('缺少计划文件：' + ', '.join(sorted(expected - set(files))))
                for module in plan['modules']:
                    extract_module_header(files[module['file']], module['name'])
                break
            except ValueError as error:
                if attempt:
                    raise ValueError(f'联合 Coder 输出无效：{error}') from error
                messages.extend([{'role': 'assistant', 'content': answer}, {'role': 'user', 'content':
                    f'工程校验失败：{error}。保持规格，修正接口或文件完整性后返回完整工程 JSON。'}])
        for relative, rtl in files.items():
            target = safe_project_path(self.runtime.run_dir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rtl, encoding='utf-8')
        self.finish(event, 'info', response=f'Generated {len(files)} coordinated model RTL files.',
                    usage=result.get('usage'))
        return files

    def run(
        self,
        planner_handoff: Path,
        *,
        existing_files: dict[str, str] | None = None,
        start_module: str | None = None,
    ) -> Path:
        incoming = self.runtime.read_handoff(planner_handoff)["payload"]
        artifacts = incoming.get("artifacts") or {}
        spec_ref = artifacts.get("spec")
        plan_ref = artifacts.get("plan")
        if not isinstance(spec_ref, str) or not isinstance(plan_ref, str):
            raise ValueError("Planner → Coder handoff 缺少 Spec 或 Plan artifact")
        effective_spec = self.runtime.read_text_artifact(spec_ref)
        plan = self.runtime.read_json_artifact(plan_ref)
        if not isinstance(plan, dict):
            raise ValueError("Plan artifact 格式无效")
        project_id = str((self.runtime.options.get("project") or {}).get("id") or "")
        project_checklist = (
            "\n\n" + RV32I_PIPELINE_CHECKLIST + "\n\n" + RV32I_L1_CODE_PATTERNS
            if project_id.startswith("rv32i5")
            else ""
        )
        project_checklist += "\n" + coder_context(project_id)
        files: dict[str, str] = {}
        sources: dict[str, str] = {}
        existing = existing_files or {}
        use_reference = (
            project_id == "rv32i5_cache"
            and self.runtime.options.get("use_l1_reference", True)
        )
        reference = load_reference(project_id) if use_reference else {}
        if use_reference:
            if plan.get("top_module") != "rv32i5":
                raise ValueError("L1 参考工程要求顶层模块为 rv32i5")
            # The original Planner output remains in plan.json for audit.  All
            # downstream agents receive the effective reference-derived plan.
            plan = build_reference_plan(reference)
            plan_ref = self.runtime.write_json_artifact("plan_reference.json", plan)
            # Recreate the whole known-good bundle; never mix a partial old run
            # or a model-generated file with incompatible reference interfaces.
            existing = {}
            start_module = None
        elif plan.get("implementation_source") == "reference":
            # A mode change on resume regenerates the entire project against
            # the reference-derived contract, with truthful provenance.
            plan = dict(plan)
            plan["implementation_source"] = "model"
            plan["notes"] = ("Model-generated implementation of the reference-derived interface contract; "
                             "no reference RTL was copied in this run.")
            plan_ref = self.runtime.write_json_artifact("plan_model_resume.json", plan)
            existing = {}
            start_module = None
        modules = plan["modules"]
        start_index = 0
        if start_module:
            for index, module in enumerate(modules):
                if module.get("name") == start_module:
                    start_index = index
                    break
        architecture_block = _architecture_block(plan)
        if project_id.startswith('rv32i5') and not use_reference and not existing and not start_module and len(modules) > 1:
            files = self._coordinated_files(effective_spec, plan, project_checklist + architecture_block)
            sources = {path: 'model' for path in files}
        for index, module in enumerate(modules):
            if module['file'] in files:
                continue
            if index < start_index and module["file"] in existing:
                files[module["file"]] = existing[module["file"]]
                sources[module["file"]] = "resume"
                continue
            if module["file"] in reference:
                rtl = reference[module["file"]]
                target = safe_project_path(self.runtime.run_dir, module["file"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rtl, encoding="utf-8")
                files[module["file"]] = rtl
                sources[module["file"]] = "reference"
                event = self.runtime.begin_event(
                    "coder", self.node_type, f"{self.title} · {module['name']}", "参考实现"
                )
                event.update(module=module["name"], file=module["file"], implementation="reference")
                self.finish(
                    event,
                    "info",
                    response=f"Wrote {module['file']} (L1 reference, {len(rtl)} chars).",
                )
                continue
            prompt = (
                f"请实现项目中模块 `{module['name']}`，写入文件 `{module['file']}`。"
                "只输出该文件的完整 SystemVerilog RTL，不要输出 Markdown 围栏或解释。\n\n"
                "项目计划（必须严格遵守 modules[].interfaces 的端口名/方向/位宽；"
                "跨模块信号在该模块中也必须使用同一套名称和宽度，不能自行改名或增删端口）。\n"
                + architecture_block
                + "语法自检：端口列表已经声明的 output/input 信号不要在模块体内再次用 logic/wire 声明；"
                "每个信号只能有一个 driver；不要出现重复声明或多驱动。\n"
                f"{json.dumps(plan, ensure_ascii=False, indent=2)}\n\n"
                f"Spec：\n{effective_spec}\n\n"
                f"本模块说明：{module['description']}\n本模块接口契约：{module['interfaces']}"
                + project_checklist
            )
            event = self.runtime.begin_event(
                "coder", self.node_type, f"{self.title} · {module['name']}", prompt
            )
            event.update(module=module["name"], file=module["file"], implementation="model")
            self.runtime.persist()
            result = self.runtime.call_model(
                event, prompt, RTL_SYSTEM_PROMPT, model_options=self.MODEL_OPTIONS
            )
            rtl = extract_rtl(result.get("answer") or "")
            if not rtl.strip() or "module" not in rtl:
                raise ValueError(f"Coder 没有为 {module['name']} 生成有效 RTL")
            target = safe_project_path(self.runtime.run_dir, module["file"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rtl, encoding="utf-8")
            files[module["file"]] = rtl
            sources[module["file"]] = "model"
            artifact_dir = self.runtime.run_dir / f"step-{event['step']:02d}-{event['node_id']}"
            (artifact_dir / "generated.sv").write_text(rtl, encoding="utf-8")
            self.save_context(plan_ref=plan_ref, last_file=self.runtime.artifact_ref(target))
            self.finish(
                event,
                "info",
                response=f"Wrote {module['file']} ({len(rtl)} chars).",
                rtl=rtl,
                reasoning=event.get("reasoning"),
                usage=event.get("usage"),
            )
        manifest = self.runtime.snapshot_rtl_manifest(files, "coder")
        for entry in manifest["files"]:
            entry["implementation"] = sources[entry["path"]]
        manifest_ref = self.runtime.write_json_artifact("rtl_manifest.json", manifest)
        self.save_context(plan_ref=plan_ref, rtl_manifest_ref=manifest_ref)
        return self.runtime.write_handoff(
            "coder",
            "tester",
            {
                "artifacts": {
                    "spec": spec_ref,
                    "plan": plan_ref,
                    "rtl_manifest": manifest_ref,
                },
            },
            label="Coder → Tester: RTL manifest",
        )
