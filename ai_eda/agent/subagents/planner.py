"""RTL Planner 子 Agent：规划模块与文件结构。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ai_eda.agent.skills.rv32i5_contract import planner_context
from ai_eda.agent.skills.rv32i5_l1_reference import build_reference_plan, load_reference
from ai_eda.agent.skills.fifo_area_power import evaluate as evaluate_fifo_skill

from .base import SubAgent
from .common import PLANNER_SYSTEM_PROMPT, extract_json_payload, validate_plan


def duplicate_interface_ports(plan: dict) -> list[str]:
    """Detect repeated explicitly declared ports in textual plan contracts."""
    issues = []
    pattern = re.compile(r'\b(?:input|output|inout)\s+(?:(?:wire|logic|reg|signed|unsigned)\s+)*(?:\[[^\]]+\]\s*)*([A-Za-z_][A-Za-z0-9_$]*)')
    for module in plan['modules']:
        seen = set()
        for name in pattern.findall(module.get('interfaces', '')):
            if name in seen:
                issues.append(f"{module['name']}: duplicate port {name}")
            seen.add(name)
    return issues


class PlannerAgent(SubAgent):
    name = "planner"
    title = "02 · RTL Planner"
    node_type = "planner"

    def _review_protocol(self, spec: str, plan: dict) -> dict:
        """Review lifecycle and architectural data sources before writing RTL."""
        prompt = (
            'Review this CPU plan before implementation. Check cross-module contracts, not RTL style. '
            'For every pipeline boundary identify the token owner and exactly when it advances, holds, '
            'is consumed, becomes empty, or is flushed. An upstream stall must not repeatedly retire '
            'an already-consumed downstream token. A consumer that advances must not see a held token '
            'as a new instruction on following cycles. An ECALL stops younger work but permits all older '
            'operations and their memory requests to drain. Verify every architectural input has a real '
            'producer or explicitly owned state: no placeholders or zero tie-offs for register values, '
            'writeback, instruction PC, or ECALL exit state. Verify request acceptance, response capture '
            'and valid lifetime agree at both endpoints, including synchronous same-edge memory replies. '
            'Preserve all spec requirements, module names and file names; do not supply RTL or a reference implementation. '
            'Return ONLY compact JSON {"issues":["short specific conflict"],'
            '"timing_contract":"complete corrected internal timing/ownership and numeric control encodings, max 4000 characters",'
            '"interface_updates":[{"module":"existing internal module name",'
            '"interfaces":"complete revised port declaration contract"}]}. '
            'At most 4 short issues and 3 affected interface_updates; use [] if no port changes are needed. '
            'Keep timing_contract concise: do not repeat ISA, bus specification or general design advice. '
            'Replace only internal implementation notes and necessary internal ports; top external ports stay unchanged. '
            'Resolve conflicts by choosing one concrete consistent design, not listing alternatives.\n\n'
            'Frozen spec:\n' + spec + '\n\nDraft plan:\n' + json.dumps(plan, ensure_ascii=False))
        event = self.runtime.begin_event('reviewer', 'model', 'Protocol contract review before Coder', prompt)
        messages = [{'role':'system','content':'You are an independent CPU protocol contract reviewer. Return JSON, never RTL.'},
                    {'role':'user','content':prompt}]
        for attempt in range(2):
            result = self.runtime.call_model_messages(event, messages,
                model_options={'thinking':False, 'max_tokens':6000})
            try:
                review = extract_json_payload(result.get('answer') or '')
                updates = review.get('interface_updates')
                notes = review.get('timing_contract')
                if (not isinstance(updates,list) or len(updates)>3 or not isinstance(notes,str)
                        or not notes.strip() or len(notes)>4000):
                    raise ValueError('provide timing_contract <=4000 characters and <=3 interface_updates')
                revised = json.loads(json.dumps(plan))
                modules = {m['name']:m for m in revised['modules']}
                for update in updates:
                    name = update.get('module') if isinstance(update,dict) else None
                    if (name not in modules or name == revised['top_module']
                            or not isinstance(update.get('interfaces'),str) or len(update['interfaces'])>5000):
                        raise ValueError('only concise existing internal interface contracts may be updated')
                    modules[name]['interfaces']=update['interfaces']
                revised['notes']=notes
                revised = validate_plan(revised)
                issues = duplicate_interface_ports(revised)
                if issues: raise ValueError('; '.join(issues))
                break
            except ValueError as error:
                if attempt: raise
                messages += [{'role':'assistant','content':result.get('answer') or ''},
                             {'role':'user','content':f'Invalid protocol review: {error}. Return corrected complete JSON.'}]
        ref = self.runtime.write_json_artifact('plan_protocol_review.json', {'source':'model', **review})
        self.finish(event, 'info', response=json.dumps(review, ensure_ascii=False), review_artifact=ref)
        return revised

    def run(self, parser_handoff: Path) -> Path:
        incoming = self.runtime.read_handoff(parser_handoff)["payload"]
        artifacts = incoming.get("artifacts") or {}
        spec_ref = artifacts.get("spec")
        if not isinstance(spec_ref, str):
            raise ValueError("Parser → Planner handoff 缺少 spec artifact")
        effective_spec = self.runtime.read_text_artifact(spec_ref)
        skill_result: dict | None = None
        skill_ref: str | None = None
        skill_prompt = ""
        project_id = (self.runtime.options.get("project") or {}).get("id")
        if project_id == "rv32i5_cache" and self.runtime.options.get("use_l1_reference", True):
            # Reference mode is a complete fixed design: its actual declarations
            # define the contract, so an unrelated model-generated plan would be
            # misleading and discarded by Coder anyway.
            prompt = "从完整 L1 参考 RTL 提取实际模块、文件和端口契约。"
            event = self.runtime.begin_event("planner", self.node_type, self.title, prompt)
            event["implementation"] = "reference"
            plan = build_reference_plan(load_reference(project_id))
            plan_ref = self.runtime.write_json_artifact("plan.json", plan)
            self.save_context(spec_ref=spec_ref, plan_ref=plan_ref, planner_skill_ref=None)
            self.finish(event, "info", response=json.dumps(plan, ensure_ascii=False, indent=2))
            return self.runtime.write_handoff(
                "planner", "coder", {"artifacts": {"spec": spec_ref, "plan": plan_ref}},
                label="Planner → Coder: reference RTL contract",
            )
        if self.runtime.options.get("planner_skill") and project_id == "stream_filter":
            skill_result = evaluate_fifo_skill(effective_spec)
            skill_ref = self.runtime.write_json_artifact("planner_skill.json", skill_result)
            skill_prompt = (
                "\n\nPlanner Skill 已运行，下面是面积/功耗预评估与架构参数。"
                "必须把 architecture 字段原样写入计划，并要求所有 Coder 严格遵守其中的 coder_directives：\n"
                f"{json.dumps(skill_result, ensure_ascii=False, indent=2)}\n"
            )
        prompt = (
            "根据下面的 Spec 规划 RTL 项目的模块与文件结构。每个模块必须能由一个文件独立实现；"
            "所有模块最终会一起用教师 TB 编译验收。每个 module 的 interfaces 必须写全端口名、方向、位宽；"
            "跨模块连接必须使用一致的信号名和位宽，生产端为 output、消费端为 input，不能只写一句总结。"
            "列出所有实际实例化的辅助模块；每个实例必须有对应计划文件，禁止遗漏内部依赖。\n"
            + ("在 notes 中冻结跨模块时序合同：每个流水寄存器由谁持有，何时 hold/bubble/flush；"
            "所有控制枚举（ALU、前递选择、写回选择）的数值含义；"
            "请求从提出、接受到响应完成的状态及元数据所有者；"
            "前递使用的已完成数据与不可用 load 数据的区别。"
            "输入反馈端口和本模块输出端口用途不同时必须使用不同名字。"
            "如有取指 Cache，明确接受 PC 和返回指令如何配对、在 stall/redirect 时如何保存；"
            "禁止仅在 notes 重述规格而不选择实现时序。\n" if str(project_id).startswith('rv32i5') else '')
            + "\n" + planner_context(project_id)
            + skill_prompt
            + f"\nSpec：\n{effective_spec}\n\n"
            "请只返回约定的 JSON 对象。"
        )
        event = self.runtime.begin_event("planner", self.node_type, self.title, prompt)
        messages = [{'role': 'system', 'content': PLANNER_SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}]
        for attempt in range(3):
            result = self.runtime.call_model_messages(event, messages)
            answer = result.get('answer') or ''
            try:
                plan = validate_plan(extract_json_payload(answer))
                issues = duplicate_interface_ports(plan)
                if issues:
                    raise ValueError('; '.join(issues))
                break
            except ValueError as error:
                if attempt == 2:
                    raise ValueError(f"Planner 规划无效：{error}") from error
                messages.extend([{'role': 'assistant', 'content': answer}, {'role': 'user', 'content':
                    f'规划接口校验失败：{error}。同一模块中输入与输出不能重名；'
                    '请为不同用途使用独立端口名，并同步更新连接。返回完整修正后的 JSON 规划。'}])
        if skill_result is not None:
            plan["architecture"] = skill_result
        if str(project_id).startswith('rv32i5') and plan.get('top_module') == 'rv32i5':
            self.runtime.write_json_artifact('plan_draft.json', plan)
            plan = self._review_protocol(effective_spec, plan)
        plan_ref = self.runtime.write_json_artifact("plan.json", plan)
        self.save_context(
            spec_ref=spec_ref,
            plan_ref=plan_ref,
            planner_skill_ref=skill_ref,
        )
        self.finish(
            event,
            "info",
            response=json.dumps(plan, ensure_ascii=False, indent=2),
            reasoning=event.get("reasoning"),
            usage=event.get("usage"),
        )
        return self.runtime.write_handoff(
            "planner",
            "coder",
            {
                "artifacts": {
                    "spec": spec_ref,
                    "plan": plan_ref,
                    **({"skill": skill_ref} if skill_ref else {}),
                }
            },
            label="Planner → Coder: Spec / Plan artifacts",
        )
