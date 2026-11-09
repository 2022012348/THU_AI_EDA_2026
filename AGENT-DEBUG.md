# AI EDA Agent · 架构与调试手册

> 这份文档是给**接手调试的 agent/工程师**看的：假设你能读源码，但需要一张准确的地图——谁调用谁、数据长什么样、失败了去哪看、哪些地方是坑。
> 所有行号基于 `42750f4`（上游 `K1ssMe520/THU_AI_EDA_2026`）＋两条本地提交（`SETUP.md`、`runs/` 备份）。行号可能漂移，**以函数名为准**。

---

## 0. 30 秒上手

```sh
cd ~/THU_AI_EDA_2026
make web                      # 起在 http://127.0.0.1:8000，Ctrl+C 结束
```

无界面触发一次 Agent（调试首选，不走浏览器）：

```sh
# 1) 提交作业，拿 job_id
curl -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"rv32i5","thinking":true,"reasoning_effort":"low",
       "max_tokens":60000,"max_repair_attempts":8,"max_calls":100}'

# 2) 轮询（前端也是 500ms 一次，见 agent-runs.js:441）
curl -s http://127.0.0.1:8000/api/agent/jobs/<job_id>

# 3) 作业结束后看落盘结果
curl -s http://127.0.0.1:8000/api/agent/runs
curl -s http://127.0.0.1:8000/api/agent/runs/<run_id>
```

一次 run 的全部证据都在 `runs/agent/<run_id>/`（`run_id` 用 **UTC** 时间戳，`agent-20261027T080948…` 其实是北京时间 16:09）。

**目录速记**

| 路径 | 作用 |
| --- | --- |
| `ai_eda/agent/orchestrator.py` | 唯一的调度器（`run_agent`） |
| `ai_eda/agent/subagents/*.py` | 五个角色 |
| `ai_eda/agent/subagents/common.py` | **所有 system prompt 的住址** + 校验函数 |
| `ai_eda/agent/runs.py` | 图校验/迁移、run 读写、续跑、设计变体 |
| `ai_eda/rtl/runner.py` | iverilog/vvp 调用、TB 输出解析 |
| `ai_eda/rtl/metrics.py` | yosys 映射 + OpenSTA 功耗 |
| `ai_eda/model/client.py` | DeepSeek 封装（thinking/temperature/重试） |
| `ai_eda/web/server.py` | HTTP + 作业线程 + 人在环通道 |
| `content/agent/simple_eda_agent.json` | 流程图（**不参与调度**，见 §2.1） |
| `runs/agent/<run_id>/` | 一次 run 的全部产物 |

---

## 1. 分层与调用关系

```
浏览器 (agent-*.js)
   │  POST /api/agent/jobs
   ▼
server.py::_execute_agent_job        ← 每个作业一个 daemon 线程（无全局单飞锁）
   │  on_event / cancel_event / request_input
   ▼
orchestrator.py::run_agent           ← 固定流水线，唯一的 while 循环
   │  建 RunContext（run 目录、artifact、handoff、事件）
   ├─► ParserAgent.run   ─┐
   ├─► PlannerAgent.run   │  每个 agent 读上游 handoff → 读 artifact
   ├─► CoderAgent.run     │  → （可选）调模型 → 写 artifact/handoff
   ├─► TesterAgent.run    │
   └─► ModifierAgent.run ─┘
              │
              ├─► rtl/runner.py::test_rtl   （iverilog / vvp / 子进程）
              └─► rtl/metrics.py::synthesize_metrics（yosys / sta）

model/client.py::ModelClient  ← 所有模型调用的唯一出口
```

**关键设计**：agent 之间**不共享内存**，只通过两种东西通信——

1. **handoff**（`handoffs/*.json`）：不可变、小、只放引用；
2. **artifact**（`artifacts/*`）：大对象（spec/plan/RTL/报告）落盘一次，按相对路径引用。

---

## 2. 调度语义（先搞清楚这几条，否则会误判"为什么没按图跑"）

### 2.1 `graph.json` 只是可视化

`content/agent/simple_eda_agent.json` 里写了 `nodes/edges/retry`，看起来像可编排的 DAG，但：

- `run_agent` 的注释明确：*"graph.json 只是该固定流程的只读可视化，不参与调度"*（`orchestrator.py:221-225`）；
- 真正的顺序是 `orchestrator.py:431-458` 的硬编码调用；
- 重试上限来自函数参数 `max_repair_attempts`（默认 8），不是 JSON 里的 `retry.max`；
- UI 保存的"设计变体"（`content/agent/designs/*.json`）**不会被执行**，`design_id` 只进 metadata（`orchestrator.py:216-218`）；
- `normalize_agent_graph`（`runs.py:75`）会把旧图压成线性链：每节点只能一个后继、一个前驱（`runs.py:252-256`），重试目标必须在验证节点之前（`runs.py:191`）。

> 调试含义：如果你改了 JSON 发现行为没变，**这是预期行为**，不是 bug。

### 2.2 上限一览

| 限制 | 值 | 位置 |
| --- | --- | --- |
| 模型调用总次数 | `max_calls` 默认 100，范围 1–1000 | `orchestrator.py:230`、`base.py:81` |
| Tester 轮次 | `max_repair_attempts + 1`，默认 9，范围 1–10 | `orchestrator.py:233` |
| Parser 补充轮次 | 3 | `common.py:115` |
| 单节点 prompt | ≤ 30000 字符（仅保存图时校验） | `runs.py:220` |
| Modifier 对话历史 | 220k 字符 / 保留最近 6 条 | `modifier.py:36-37` |
| Modifier 输出解析重试 | 2 次（第 2 次追加纠错消息） | `modifier.py:181` |
| 后台作业表 | 最多 24 个，超出按更新时间淘汰 | `server.py:74` |
| 单次输出 token | 默认 60000（Agent 入口） | `server.py:234` |

### 2.3 并发与线程

- 每次 `POST /api/agent/jobs` 起一个 `threading.Thread(daemon=True)`（`server.py:833-840`）；
- **没有全局单飞锁**：同时点两次会并行跑两个 run（各自独立 run 目录，互不干扰，但会抢 CPU 和 API 配额）；
- `_AGENT_JOBS` 是内存字典，进程重启即丢；**落盘的 `runs/` 才是真相**；
- 事件通过 `on_event` 回调写进内存 job，前端 500ms 轮询 `GET /api/agent/jobs/{id}`（SSE 只用于单次生成，见 `server.py:503`）。

### 2.4 暂停（人在环）与取消

```
Parser 判 spec 不充分
  → runtime.mark_waiting(event, request)      # event.status = "waiting_input"
  → request_input(request) 阻塞（0.2s 轮询 threading.Event，server.py:331-356）
  ↔ POST /api/agent/jobs/{id}/input  {"response":"..."}   # server.py:846
  → 返回文字 → Parser 追加进 supplements，重新调模型
```

- `request_input=None`（无交互通道，比如脚本调用 `run_agent` 直接调）时，Parser 会抛 `ValueError`（`parser.py:110-114`）；
- 取消：`POST /api/agent/jobs/{id}/cancel` 置 `cancel_event`，`check_cancel()` 在流式每个 chunk 检查（`base.py:101`），抛 `AgentCancelled` 后 orchestrator 把未完成事件标 `cancelled`（`orchestrator.py:500-547`）；
- 取消后 run 目录**保留**，可续跑。

### 2.5 续跑（resume_from）

`_load_resume_source(run_id)`（`orchestrator.py:44-115`）会：

1. 读上一次的 `artifacts/effective_spec.md`（没有则 `spec.md`）、`plan.json`、`parser_result.json`；
2. 从 `events.json` **倒序**找第一个 `status ∈ {failed, cancelled, running}` 的事件，把它当作中断点；
3. 按中断点决定从哪继续：`parser` / `planner` / `coder` / `tester` / `modifier`；
4. `coder` 续跑会用事件标题里 `" · "` 之后的部分当模块名（`orchestrator.py:98`），**依赖标题格式**——标题在 `coder.py:110` 拼成 `f"{self.title} · {module['name']}"`，改标题格式会破坏续跑；
5. `modifier` 续跑需要上次存在 `tester_to_modifier_attempt*.json`（`orchestrator.py:127-130`）。

> 坑：如果上次是**被 kill 的**，最后一个事件是 `running`，续跑会认为断在该事件上——这是有意的，但 `running` 的 coder 事件没有 `generated.sv`，会退化成重跑该模块。

---

## 3. 磁盘契约（Codex 改代码最容易破坏的地方）

### 3.1 一次 run 的目录

```
runs/agent/agent-20261027T080948039158/
├── events.json                    # 全量事件快照（原子写，UTC 时间戳）
├── graph.json                     # 本次使用的图（快照，只读）
├── metadata.json                  # 项目、模型、参数、attempts、状态
├── result.json                    # 最终结果（passed/summary/metrics/spec/plan/files…）
├── agents/<name>/context.json     # 每个 agent 的私有记忆
├── artifacts/
│   ├── spec.md                    # 原始 spec（不可变）
│   ├── effective_spec.md          # 原 spec + 用户补充 + parser addendum
│   ├── parser_result.json         # {supplements, rounds, sufficient}
│   ├── plan.json                  # Planner 输出（+ architecture）
│   ├── rtl_manifest.json          # Coder 输出
│   ├── rtl_manifest_attemptN.json # Modifier 每次重写的清单
│   ├── generated_attemptN.sv      # 第 N 轮合并后的单文件（喂给 iverilog）
│   └── planner_skill.json         # 仅 stream_filter + planner_skill=true
├── handoffs/
│   ├── spec_to_parser.json
│   ├── parser_to_planner.json
│   ├── planner_to_coder.json
│   ├── coder_to_tester.json
│   ├── tester_to_modifier_attempt1.json / attempt2…
│   ├── modifier_to_tester_attempt1.json / attempt2…
│   └── tester_to_summary_attempt3.json     # 通过时
├── project/rtl/*.sv               # Coder/Modifier 实际写出的工程文件
├── tester-01/…                    # 每轮：test_report.json + activity.vcd
├── retest/                        # 手动 Retest 的产物
└── step-XX-<node_id>/             # 每次模型调用
    ├── prompt.md                  # 实际发给模型的 user prompt
    ├── conversation.json          # 完整 messages（含 system）
    ├── raw_response.txt           # 模型原始回答
    ├── reasoning.txt              # 思考链（若有）
    └── generated.sv               # 仅 coder/modifier
```

### 3.2 handoff schema（**不要改，改了就续跑/UI 全挂**）

`base.py:196-224` 写入，`base.py:226-240` 读取校验：

```json
{
  "schema_version": 1,
  "edge_id": "coder_to_tester",
  "source": "coder",
  "target": "tester",
  "attempt": null,
  "label": "Coder → Tester: RTL manifest",
  "created_at": "2026-10-27T08:12:33.123Z",
  "payload": {
    "attempt": 1,
    "summary": "...",
    "artifacts": {
      "spec": "artifacts/effective_spec.md",
      "plan": "artifacts/plan.json",
      "rtl_manifest": "artifacts/rtl_manifest.json",
      "report": "artifacts/../tester-01/test_report.json",
      "combined_rtl": "artifacts/generated_attempt1.sv"
    }
  }
}
```

硬规则：

- **文件名 = `{source}_to_{target}[_attemptN].json`**，已存在就抛错，绝不覆盖（`base.py:221-222`）；
- `payload.artifacts` 里**只放相对 run 目录的路径**，`artifact_ref` 拒绝越界（`base.py:158-164`）；
- `read_handoff` 校验 `schema_version == 1`、`payload` 是 dict；
- 同一个 `(source,target,attempt)` 只能出现一次 → 续跑时要靠 `attempt` 错开（见 `orchestrator.py:339-342`）。

### 3.3 事件（events.json）字段

必填：`run_id / step / node_id / node_type / title / prompt / status / attempt / started_at`；
完成时补：`duration_ms / finished_at / response / raw_response / reasoning / usage / output_tokens`；
按角色追加：`call_index / conversation_messages / streaming`（模型）、`report / feedback`（Tester）、`rtl`（Coder）、`input_request / input_response`（Parser 暂停）、`modifier_validation_error`（Modifier）、`conversation_turns`。

`status` 取值：`running | info | passed | failed | waiting_input | cancelled`。

> 注意：`persist()` 每次把**整个 events 列表**重新序列化写盘（1 秒节流，`base.py:121-123`）。一次 run 的 `events.json` 能到 3 MB，流式期间每秒重写一次是已知性能点（见 B6）。

### 3.4 Tester 报告 schema（`test_report.json`）

```json
{
  "task_name": "agent_rv32i5",
  "rtl_path": "/…/generated_attempt1.sv",
  "passed": false,
  "stage": "compile | simulation",
  "return_code": 1,
  "stdout": "...", "stderr": "...",
  "timed_out": true, "timeout_seconds": 20,
  "trace": [ {"cycle": 2481, "test": "t13_dft", "event": "bin", "…": "…"} ],
  "checks": [ {"name": "t02_alu_r", "detail": "x4 期望 0x… 得到 0x…"} ],
  "cpu_capability": {"declared": 0, "verified": 0, "expected_level": 0},
  "test_suites": [ {"name": "base", "passed": false, "skipped": false, "checks": 136} ],
  "performance": {"benchmarks": [ {"benchmark": "crc32", "cycles": 1200, "instructions": 400, "cpi": 3.0} ]},
  "metrics": { …见 §5.3… }
}
```

判定规则（`runner.py:385-401`）：

1. `vvp` 返回码 0 → `passed=True`；
2. **任一未 skip 的 suite `passed=false` → 强制改回 `passed=False`**；
3. 超时不是返回码，而是独立分支，`timed_out=true` 且只塞一条 `simulation_timeout` check。

### 3.5 Plan schema（`plan.json`）

```json
{
  "project_name": "rv32i5_pipeline",
  "top_module": "rv32i5",
  "modules": [
    {"name": "rv32i5", "file": "rtl/rv32i5.sv",
     "description": "…",
     "interfaces": "input logic clk; input logic rst_n; output logic [31:0] imem_addr; …"}
  ],
  "notes": "…",
  "architecture": { "parameters": {…}, "coder_directives": ["…"], "reference_structure": {…} }
}
```

校验（`common.py:158-199`）：模块名 `^[A-Za-z_]\w*$`、文件 `^[A-Za-z0-9_./-]+\.sv$`、名字/文件去重、`top_module ∈ modules`、`interfaces` 截断 1000 字符。
**`interfaces` 是下游唯一的接口契约来源**，Coder 逐模块生成、Modifier 修复都以它为准。

---

## 4. 五个角色：prompt 逐字 + 拼装 + 校验

> 改 prompt 前请先看这一节。所有 system prompt 都在 `ai_eda/agent/subagents/common.py`，`RTL_SYSTEM_PROMPT` 在 `ai_eda/model/prompts.py`。

### 4.1 Parser（`parser.py`，节点 `parser`）

**system**（`common.py:12-30`，逐字）：

```
You are the Spec Parser of a digital IC design agent.
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
Do not put the full original spec in spec_addendum. Do not return Markdown fences or extra text.
```

**user**（`parser.py:41-55`）＝固定中文指令 + `固定 Spec:` + `用户补充:` + `已有 Parser 补充/修正:`，要求"只返回补充/修正，不要重写或缩短原 Spec"。

**行为**：

- 每轮 `rounds += 1`，>3 抛错（`parser.py:38`）；
- 解析 JSON（`extract_json_payload`，兼容 ```` ```json ```` 围栏），**失败直接抛 ValueError，不重试**；
- `sufficient` 判定：`parsed["sufficient"] is True and not missing and not questions`（`parser.py:64`）——模型说 true 但给了问题，仍算不充分；
- 兼容旧字段 `refined_spec`（`parser.py:67-69`），当作 addendum；
- 拼装：`原spec + "## 用户补充" + "## Parser 补充与修正（优先于上文冲突内容）"`（`parser.py:17-24`）；
- 不充分且无交互通道 → 抛错；有通道 → `mark_waiting` 后阻塞。

**真实输出样例**（`runs/…/step-01-parser/raw_response.txt`）：`{"sufficient": true, "missing": [], "questions": [], "spec_addendum": "## 实现假设（非阻断）\n- halt-pending 期间 PC 冻结…"}`。

### 4.2 Planner（`planner.py`，节点 `planner`）

**system**（`common.py:32-36`）：

```
You are the RTL Planner of a digital IC design agent.
Given the frozen spec, plan the project module and file structure. The agent will write each file separately.
Return ONLY a JSON object:
{"project_name": "...", "top_module": "...", "modules": [{"name": "module_name", "file": "rtl/module_name.sv", "description": "short responsibility", "interfaces": "complete port contract: every port name, direction and width; for each inter-module signal use the same name/width in all modules"}], "notes": "..."}
Use only relative paths ending in .sv. Every module must be implementable in one file. The interfaces field is the interface contract: list every port name, direction and width, and use identical names/widths for a signal in every module. Do not return Markdown fences or extra text.
```

**user**（`planner.py:38-45`）＝中文指令（每模块一文件、interfaces 必须写全端口）+ 可选 skill 块 + `Spec：{effective_spec}`。

**Planner Skill**（`planner.py:30-37`）：仅当 `options.planner_skill=True` **且** `project_id == "stream_filter"` 时运行 `fifo_area_power.evaluate(spec)`，把结果写 `artifacts/planner_skill.json`，并把 `architecture` 字段强制合进 plan（`planner.py:52-53`）——**模型不能推翻 skill 选的架构参数**。

### 4.3 Coder（`coder.py`，节点 `coder`，**每模块一次调用**）

**system**＝全局 `RTL_SYSTEM_PROMPT`（`model/prompts.py:7-12`）：

```
You are a digital IC engineer. Follow the user specification exactly. Return only the requested RTL source code, without Markdown fences or explanation. Keep port lists and module interfaces consistent. Do not redeclare an output/input port inside the module body; every net must have exactly one driver.
```

**user**（`coder.py:96-108`）依次是：

1. `请实现项目中模块 \`{name}\`，写入文件 \`{file}\`。只输出该文件的完整 SystemVerilog RTL…`
2. `project 计划（必须严格遵守 modules[].interfaces…）` + `_architecture_block(plan)`（有 skill 时）
3. `语法自检：端口列表已声明的 output/input 不要再在模块体内声明…每个信号只能一个 driver`
4. **完整 plan JSON**（所以每个模块的 prompt 约 32k 字符）
5. `Spec：{effective_spec}`
6. `本模块说明 / 本模块接口契约`
7. **仅 RV32I 项目**（`project_id.startswith("rv32i5")`）：追加 `RV32I_PIPELINE_CHECKLIST` + `RV32I_L1_CODE_PATTERNS`（见 §6.2）

**模型参数**：`MODEL_OPTIONS = {"thinking": False}`（`coder.py:41`）——作者注释说明：60k 输出预算可能全被 reasoning 吃掉，导致没有 RTL 正文。

**参考实现旁路**（`coder.py:68, 81-95`）：`project_id == "rv32i5_cache"` 且 plan 的 `rtl/xxx.sv` 命中 `content/agent/skills/rv32i5_l1_reference/` 时，**不调模型**，直接写文件，事件标题 `"参考实现"`，`response` 为 `Wrote …(L1 reference, N chars).`。

**输出**：`extract_rtl()`（`runner.py:112`，优先取 ```` ```verilog ```` 围栏内内容，否则全文）；空或没有 `module` 关键字 → 抛错。最后写 `artifacts/rtl_manifest.json` + `coder_to_tester` handoff。

### 4.4 Tester（`tester.py`，节点 `tester`，**不调模型**）

纯代码：合并文件 → `test_rtl()` → `save_report()` → 按 `passed` 决定 handoff 目标是 `summary` 还是 `modifier`。

事件里的 `prompt` 只是给人看的字符串：`f"Round {attempt}: compile {len(files)} project files and run the fixed teacher TB; generate power activity and synthesized area as well."`（`tester.py:46-49`），**不会发给模型**。

`feedback` 字段（`tester.py:79`）＝ `report_feedback(report)` 的结果，就是 Modifier 下一轮看到的"失败摘要"。

### 4.5 Modifier（`modifier.py`，节点 `modifier`，**持久多轮对话**）

**system**（`common.py:86-113`，逐字）：

```
You are the RTL Modifier of a digital IC design agent.
You work in a persistent multi-turn repair conversation. The first user message contains the frozen spec, project plan, current RTL files, and the first failure report; later user messages contain the next Tester failure and the current file snapshot.
Your job is to diagnose the root cause and modify only the files that need changes.

Rules:
- Match the Planner interfaces exactly. Never rename ports, modules, files, or parameters.
- For compile failures, fix every error in stderr, including hierarchy/port/width errors.
- For simulation failures, use the failing checks and trace to find the root cause; do not guess or weaken behavior.
- Preserve already-correct logic. A small targeted patch is better than rewriting the project.
- Do not add external IPs, simulation-only constructs, or modify the teacher TB.
- Keep diagnosis focused: identify the minimal root cause, avoid restating the spec or exploring unneeded alternatives.
- Build a short failure matrix before editing: failing check -> expected/actual -> affected module(s). Cover every failed check category, not just the first one.
- If the same check failed in the previous repair round, do not repeat the same patch. Re-read the failing trace and change the data path or state transition that produces the mismatch.
- RV32I load/store failures: explicitly verify little-endian byte lanes, sign/zero extension, SB/SH byte enables and replicated wdata, cache refill merge, write-through ordering, and load-use forwarding.
- RV32I reset/control failures: verify synchronous reset gating of dmem_valid, pipeline valid/flush, PC redirection, and halted/exit_code timing.
- If many tests time out waiting for halted while imem_addr advances, prioritize the ECALL→halt path: ID decode, is_ecall propagation through EX/MEM/WB, WB halted/exit_code commit, IF freeze, and synchronous reset. Do not assume a cache or load/store bug from the timeout alone.
- Before returning JSON, self-check each failed check from the latest report and state the repair in notes. Do not return files that only address a subset.
- Compare every returned content with the current file snapshot. At least one returned file MUST differ from the snapshot; returning an unchanged file is an invalid no-op patch.
- If a previous patch did not change behavior, do not repeat it; change the root-cause hypothesis and the implementation strategy.
- Return ONLY a JSON object; no Markdown fences, no prose outside JSON.

Return schema:
{"files": [{"path": "rtl/foo.sv", "content": "full SystemVerilog file content"}], "notes": "short diagnosis and repair summary"}
You may return only files that need changes, but each returned file must contain its complete content.
```

其后**无条件**拼接 `RV32I_PIPELINE_CHECKLIST` + `RV32I_L1_CODE_PATTERNS`（`common.py:113`）——注意：**两个非 RV32I 项目（stream_filter）也会看到 RV32I 提示**，这是当前实现的一个（无害但冗余的）副作用。

**首轮 user**（`modifier.py:60-84`）：修复策略 7 条 + 完整 plan + architecture + **当前所有文件全文**（JSON）+ spec（**截断 45000 字符**）+ 第一次失败报告。
**后续 user**（`modifier.py:92-99`）：`第 N 轮修复…` + 最新失败报告 + 当前文件快照，明确"不要重新规划"。

**对话管理**：

- 历史存 `agents/modifier/context.json` 的 `conversation`；
- 每次调用前 `_trim_history`：总长 > 220k 且条数 > 8 时，保留 `system + 第 1 条` + 最近 6 条（`modifier.py:117-132`）；
- 每轮把模型回答 append 进历史（所以它能"记得"自己上次改了什么）。

**输出校验**（关键防呆）：

1. `extract_json_payload` → `validate_modifier_files(payload, plan)`：路径必须在 plan 内、content 必须含 `module`（`common.py:202-219`）；
2. `_effective_changes` **剔除与当前文件逐字节相同的条目**（`modifier.py:19-27`）；
3. 剔除后为空 → 抛 `ValueError("…没有产生任何实际修改…")`，追加纠错消息重试一次；第二次仍失败 → 整个 run 失败（`modifier.py:219-222`）。

**真实表现**（`step-13-modifier`）：返回了 `forwarding_unit.sv`（原样）+ `ex_stage.sv`（真改），前者被 `_effective_changes` 丢弃，只写了后者。

---

## 5. 工具层：编译器、仿真器、综合、功耗

### 5.1 `test_rtl()` 的完整外部命令

编译（`runner.py:331-340`）：

```
iverilog -g2012 [-DRV32I_FEATURE_PORTS] -I <tb目录> -s <testbench_top> -o <tmp>/simulation.vvp <tb.sv> <rtl.sv>
```

- `-DRV32I_FEATURE_PORTS` 只在 **RTL 顶层真的声明了 `dbg_features`** 时才加（`_cpu_feature_compile_flags`，`runner.py:22-33`，注释里先剥离注释/字符串再正则匹配）；
- `-s` 固定为项目配置里的 `testbench_top`；
- 超时 `timeout_seconds`（默认 20s），编译失败 → `stage="compile"`，**保留 stdout/stderr 原文**。

仿真（`runner.py:355-365`）：

```
vvp <tmp>/simulation.vvp [+expected_cpu_level=N]
```

- `+expected_cpu_level` 只在 `project.expected_cpu_level` 存在时传（L0–L3，`runner.py:356-357`）；
- 超时 → 单独分支，`timed_out=true`，check 名 `simulation_timeout`。

### 5.2 教师 TB 的机器可读协议（`runner.py:36-104`）

| 行前缀 | 解析结果 |
| --- | --- |
| `AI_EDA_TRACE\|k=v\|k=v` | `trace[]`，`cycle` 转 int，其余保留字符串 |
| `CHECK: name — detail` | `checks[]`（`—` 是 U+2014，注意不是 `-`） |
| `AI_EDA_CAPABILITY\|declared=…\|verified=…\|expected=…` | `cpu_capability`（同时补 `*_level` 别名） |
| `AI_EDA_SUITE\|name=…\|passed=1\|skipped=0\|checks=N` | `test_suites[]`（`passed` 兼容 1/true/PASS/pass） |
| `AI_EDA_PERF\|benchmark=…\|cycles=…\|instructions=…` | `performance.benchmarks[]`，自动算 `cpi`/`ipc` |

`passed` 的最终判定在 `runner.py:400-401`：**任一未 skip 的 suite 失败即整体失败**。

### 5.3 `synthesize_metrics()` 与 gscl45nm

`metrics.py:111-200`：

1. Liberty 来自 `vpadanalyzer` 包（`_library_path`，`metrics.py:24-28`；`verilog-pad-analyzer==0.0.7` 自带 `config/gscl45nm.lib`）；
2. Yosys 脚本（`metrics.py:71-79`）：`read_verilog -sv` → `hierarchy` → `proc;opt;fsm;opt;memory;opt` → `techmap;opt` → `dfflibmap -liberty` → `abc -liberty` → `stat -liberty` → `write_verilog -noattr`；
3. 面积用正则从 `Chip area for top module '<x>': N` 抓（抓不到再试 `for module`）；
4. `_sta_safe_netlist`：把 Yosys 的转义标识符换成 `\esc_N `、去掉 `wire/reg signed`（OpenSTA 解析器不兼容），写 `mapped_sta.v`；
5. sta 脚本：`read_liberty` → `read_verilog` → `link_design <top>` → `read_sdc`（固定 `create_clock -period 10`）→ `read_vcd -scope <power_tb_top>/dut` → `report_power`；
6. 输出含 `status`（`ok|area_only|failed|unavailable`）、`area`、`internal/switching/dynamic/leakage/total_power_w`、`power_reason`。

**sta 可执行文件查找顺序**（`metrics.py:30-34`）：`<repo>/.tools/opensta/bin/sta`（可执行）→ `PATH` 里的 `sta`。`.tools/opensta` 是指向 `~/.local` 的软链，**不依赖 PATH**。

### 5.4 功耗 TB

有 `power_testbench_path` 时（`runner.py:402-414`）：用 `-s <power_testbench_top>` 再编译一次，跑 `vvp +vcd=<run_dir>/activity.vcd`，然后把 VCD 丢给 sta。VCD scope 固定 `f"{power_testbench_top}/dut"`（`runner.py:418`）——**这意味着 power TB 里 DUT 实例必须叫 `dut`**。

---

## 6. 项目与 RISC-V 档位系统

### 6.1 项目注册表（`projects.py`）

| id | 任务 | TB | `expected_cpu_level` | 说明 |
| --- | --- | --- | --- | --- |
| `stream_filter`（默认） | FIFO + checksum | `tb_agent_stream_filter` | — | 支持 Planner Skill |
| `rv32i5` | L0 五级流水 | `tb_agent_rv32i5` | 0 | |
| `rv32i5_cache` | L1 I/D Cache | 同上 | 1 | 有 L1 参考实现旁路 |
| `rv32i5_predict` | L2 Cache+预测 | 同上 | 2 | |
| `rv32i5_ooo` | L3 乱序 | 同上 | 3 | |

四个 RV32I 档位**共用同一 TB**（`content/tasks/homework_rv32i5/tb.sv` 只是壳，内容在 `tb/*.svh`，约 2700 行），靠 `+expected_cpu_level` 决定哪些 suite 必须过。

### 6.2 实际生效的 RV32I 提示注入（`common.py:74-84, 38-72`）

- `RV32I_PIPELINE_CHECKLIST`（10 条硬检查）：单拍 `resp_valid` 必须先无条件捕获、stall 时不能清 valid、ECALL 必须活到 WB、`line_data[{wsel,5'b00000} +: 32]`、store merge、refill 不许中止、I-Cache word3 用当拍响应、**双前递路径（01=MEM/WB，10=EX/MEM）**、JAL/JALR 的 EX/MEM 结果必须是 pc4、同步复位。
- `RV32I_L1_CODE_PATTERNS`（6 段可抄代码骨架）：IF 响应分支顺序、MEM 响应、DCache 字选择、ICache refill、EX 前馈、halt 提交。
- 注入位置：**Coder**（`coder.py:61-65`，仅 `rv32i5*`）和 **Modifier**（`common.py:113`，无条件）。

### 6.3 写好了但**没接线**的 skill（调试时别被误导）

| 文件 | 状态 | 证据 |
| --- | --- | --- |
| `skills/cpu_diagnostics.py`（`summarize_cpu_report` / `failure_fingerprint` / `failure_score`） | **未被 import** | `grep -rn "cpu_diagnostics" ai_eda`（除自身外无结果） |
| `skills/rv32i5_contract.py`（tier 契约、`describe_tier_context`） | **未被 import** | 同上 |

也就是说：目前 Agent 的失败反馈**没有**走"确定性修复包 + 失败指纹"，`describe_tier_context` 的档位契约注入也**没有**进 prompt。这两块是"预留能力"，谁要用得自己接线（建议接在 `report_feedback` 与 `planner/coder` 的 prompt 拼装处）。

### 6.4 真实生效的另外两个

- `fifo_area_power.py` → `planner.py:8,31`（仅 stream_filter + 开关打开）；
- `rv32i5_l1_reference.py` → `coder.py:10,68,81`（仅 rv32i5_cache）。

---

## 7. 模型调用层（`model/client.py`）

| 项 | 行为 |
| --- | --- |
| 模型 | `MODEL_NAME = "deepseek-flash"`（`client.py:25`），`BASE_URL = https://api.deepseek.com` |
| 鉴权 | `resolve_api_key()`：`.api_key` 文件优先，不存在才读 `DEEPSEEK_API_KEY/DSV3_KEY/LLM_API_KEY`；文件存在但为空 → 报错，**不回退环境变量** |
| thinking | `extra_body={"thinking":{"type":"enabled"/"disabled"}}` 显式发送，保证可复现 |
| temperature | **仅 thinking=False 时发送**；thinking=True 时发 `reasoning_effort`（服务端忽略 temperature） |
| 空响应 | 非 length 截断时自动重试 1 次；`finish_reason=length` 直接报错并给"提高 max_tokens / 关 thinking"的建议 |
| 流式 | `stream_chat_detail` 逐 chunk yield `reasoning` / `answer` / `done`；`done` 里带 usage、finish_reason |
| 工具调用 | `generate_with_tools`（function calling 循环，max_rounds=6）——**Agent 流程没用到**，只在潜在扩展里 |

Agent 侧的有效参数优先级：`RunContext.options`（全局）→ `MODEL_OPTIONS`（Coder/Modifier 强制 `thinking=False`）→ `ModelClient(...)`。

---

## 8. 已知问题清单（按调试价值排序）

> 每条都给"症状 / 定位 / 影响 / 建议"。**B1、B2 会直接影响修复质量**。

### B1 · 失败反馈里混入噪声（`common.py:226-242`）

`trace_mismatches` 把 trace 行里**任何** `expected_*` 字段当成"实际值应等于"的断言：

```python
for key, value in row.items():
    if not key.startswith("expected_"): continue
    actual_key = key.removeprefix("expected_")
    actual = row.get(actual_key) or row.get(f"out_{actual_key}")
    if actual is not None and str(actual) != str(value): ...
```

但 TB 的 `t13_dft` 行本身就带 `expected_mag`（自检信息），于是真实 run 的反馈里出现 6 条
`cycle 2481 · bin: mag=-1263225674 (expected 0)` 这种**与失败无关的行**，占掉 12 条配额的一半。

- 影响：Modifier 的注意力被分散；12 条上限被噪声吃掉。
- 建议：只认 `test` 在失败 check 集合内的行，或只认 `out_*` / `actual_*` 前缀；改完用 `tester-01` 的 report 做回归。

### B2 · halt 超时提示重复且触发过宽（`common.py:267-286`）

`feedback` 里同时出现两段 halt 提示（`HALT-TIMEOUT 诊断提示：…` 和 `HALT-TIMEOUT: …`），且触发条件是 `detail` 里含"等待 halted 超时"的 check ≥2 —— 在有多条超时类 check 的场景下，即使根因是前递/load-store，也会被引导去看 ECALL。真实 run 里 Modifier 没被带偏（它自己找到了前递 bug），但这是运气。

- 建议：合并成一段；或按 `failure_score` 排序后只在"最大失败类别是超时"时提示。

### B3 · `MAX_TEST_ATTEMPTS` 是死常量（`common.py:116`）

值 9，但全仓库无人引用；真实上限是 `max_repair_attempts + 1`。删掉或改名为 `DEFAULT_MAX_TESTER_ATTEMPTS` 并在 orchestrator 引用，避免"改了这个以为生效"。

### B4 · L1 参考实现按**文件名**精确匹配（`coder.py:68, 81`）

`load_reference()` 返回 `{"rtl/icache.sv": …}`；Planner 若把文件命名成 `rtl/l1_icache.sv`，fallback **静默失效**，退化成纯模型生成，而且没有任何日志提示。

- 建议：命中 0 个文件时记一条 `info` 事件或 warning。

### B5 · `events.json` 每秒全量重写（`base.py:121-123` + `orchestrator.py:254-273`）

`persist()` 把整个 events 列表（含流式中的半截 response）序列化后原子替换。32k 字符的 coder prompt × 11 次 + 3MB 上限，在 SSD 上尚可，但**每轮都会写全量**，长 run（L3）会明显拖慢。

- 建议：改为增量 append（NDJSON）或降低频率（如 3s / 仅在事件开始结束时）。

### B6 · 续跑依赖事件标题格式（`orchestrator.py:98`）

```python
module_name = title.rsplit(" · ", 1)[-1] if stage == "coder" and " · " in title else None
```

标题在 `coder.py:110` 拼成 `f"{self.title} · {module['name']}"`。任何人改标题分隔符/顺序，续跑会从错误模块开始或从第 0 个模块重来。

- 建议：在事件里显式存 `module` 字段，别解析标题。

### B7 · 无单飞锁，并发 run 会互相抢资源（`server.py:810-845`）

同时点两次会并行跑两个 Agent，共享同一份 `runs/` 根目录（目录不冲突），但会争 DeepSeek 速率、CPU 和 iverilog 临时目录。UI 没有"已有作业在跑"的拦截。

- 建议：加 `if any(job running): 409`，或在前端禁用按钮。

### B8 · Tester 失败时 report 全量进 events（`tester.py:77-79`）

`report` 里有 `stdout/stderr` 原文（RV32I 一轮可到 500KB+），直接塞进事件 → `events.json` 膨胀。UI 渲染也会卡。

- 建议：事件里只放 `summary + checks[:N] + metrics`，完整报告留在 `tester-NN/test_report.json`（已经有了）。

### B9 · Parser 的 `sufficient` 语义有冗余（`parser.py:64`）

模型返回 `sufficient=true` 但同时给了 `missing/questions` 会被判为不充分并去问用户。这符合"宁可多问"的设计，但 prompt 里说"When only non-blocking gaps remain, set sufficient=true, missing=[], questions=[]"，模型常会两边都填，导致**不必要的人工暂停**。观察到的真实行为是 L0/L1 spec 都直接 sufficient，但 L3 长 spec 更容易触发。

### B10 · Modifier 的 spec 截断（`modifier.py:81`）

`effective_spec[:45000]`——L3 的 spec（426 行）加上 addendum 可能逼近该值；截断后 Modifier 看不到尾部要求（通常是测试/验收章节）。建议改成"按章节截断 + 保留末尾"或直接引用 artifact 路径让模型自己读（当前流程没有文件读取工具，所以只能靠截断）。

---

## 9. 调试手册：症状 → 先看哪里

| 症状 | 先看 | 常见原因 |
| --- | --- | --- |
| Job 立刻 failed，错误含 "Spec 需要用户补充" | `events` 里 parser 事件 + `step-01-parser/raw_response.txt` | 走了无交互通道；或模型真的判不充分 |
| "Parser 返回格式无效" | 同上 raw_response | 模型输出了非 JSON（含解释文字/围栏） |
| "Planner 规划无效：…" | `step-02-planner/raw_response.txt` | 模块名/路径不合法、top_module 不在 modules、重复文件 |
| "Coder 没有为 X 生成有效 RTL" | 该 step 的 `raw_response.txt` + `usage.finish_reason` | `finish_reason=length`（预算耗尽）；模型只给了片段 |
| compile 失败 | `tester-NN/test_report.json` 的 `stderr` | 端口不匹配、重复声明、iverilog 语法限制（如嵌套 part-select） |
| simulation 失败 | `checks[]` + `trace[]` | 逻辑错；先按 check 名分组（`t01_reset`/`t05_forward`/`t06_load_store`…） |
| 仿真超时 | `timed_out=true`、`stdout` 尾部 | 没停机（ECALL 未提交）、死循环、握手卡死 |
| 功耗 `failed` | `metrics.power_reason` + `opensta_output` | VCD 缺 timescale（`Unknown timescale unit`）、scope 不匹配（DUT 不叫 `dut`）、netlist 解析失败 |
| "Modifier 修复无效" | `agents/modifier/context.json` + `modifier_validation_error` | 返回了空补丁/计划外文件/非法 JSON |
| 续跑从错误位置开始 | 上次 `events.json` 最后几条 | 最后事件是 `running`（被 kill），或标题格式变了（B6） |
| 前端一直转圈 | `GET /api/agent/jobs/{id}` 的 `status` | 作业线程异常但前端没收到；看服务端 stderr |
| 端口被占 | `lsof -nP -iTCP:8000 -sTCP:LISTEN` | 上次 `make web` 没退；`pkill -f "ai_eda serve"` |

**必会的三条命令**

```sh
# 看一次 run 的骨架（哪步失败、耗时、token）
python3 - <<'EOF'
import json; d=json.load(open('runs/agent/<run_id>/events.json'))
print(d['status'], d.get('error'))
for e in d['events']:
    print(f"{e['step']:>2} {e['node_id']:<9} {e['status']:<9} att={e.get('attempt')} {e.get('duration_ms')}ms tok={e.get('output_tokens')}")
EOF

# 单独重跑某轮的教师 TB（不改 RTL）
.venv/bin/python -m ai_eda retest --run-dir runs/agent/<run_id>

# 只用已有 RTL 重算面积/功耗
.venv/bin/python - <<'EOF'
from pathlib import Path
from ai_eda.rtl.metrics import synthesize_metrics
print(synthesize_metrics(Path('runs/agent/<run_id>/tester-01/../project/rtl/rv32i5.sv')))
EOF
```

---

## 10. 修改禁区（碰之前先想清楚）

1. **不要改 handoff 的 schema / 文件名规则**（`schema_version`、`{source}_to_{target}`、attempt 后缀）——续跑、UI、`list_agent_handoffs` 全都依赖。
2. **不要改 `runs/` 目录结构**——`retest_agent_run`、`_load_resume_source`、`list_agent_runs`、`_handoff_artifact_previews` 都按固定相对路径找文件。
3. **不要动 `.api_key`**（600 权限、gitignore）；`.tools/opensta` 是软链，`metrics.py` 靠它找 sta。
4. **不要给 Coder 默认打开 thinking**——除非同时把 `max_tokens` 提到 100k+，否则 60k 会被 reasoning 吃掉。
5. **不要删除 `event["prompt"]`**——UI 的"步骤详情"和 Parser 续跑都读它。
6. 改 prompt 时注意 **Modifier 的 system 是 `common.py:113` 拼接的**（`MODIFIER_SYSTEM_PROMPT + 空行 + CHECKLIST + 空行 + PATTERNS`），只改前者不会影响后两段。

**加一个新角色（若要做）**：

1. `subagents/<name>.py` 继承 `SubAgent`，实现 `run(input_handoff) -> output_handoff`；
2. 在 `orchestrator.py` 的固定链里插入调用（注意 handoff 文件名要唯一）；
3. 若要让它可重试，改 `while True` 那段与 `max_*` 参数；
4. 更新 `graph.json` 仅影响可视化，**不影响执行**。

---

## 11. 真实 run 参考（`agent-20261027T080948039158`）

RV32I L0，5 分 19 秒，13 次模型调用，3 轮 Tester：

| # | 步骤 | 耗时 | token | 结果 |
| --- | --- | --- | --- | --- |
| 1 | parser | 19.5s | 2.4k | sufficient + 6 条假设 |
| 2 | planner | 138s | 26.8k | 9 模块 |
| 3-11 | coder ×9 | 4.7–14.5s | 0.5–3.5k | 顶层最贵 |
| 12 | tester-01 | 3.1s | — | fail：136 checks（前递、load/store） |
| 13 | modifier-01 | 59.4s | 4.6k | 修 `ex_stage.sv` 前递 mux 反接 |
| 14 | tester-02 | 3.7s | — | fail：`t06_load_store` 字节 lane |
| 15 | modifier-02 | 11.5s | 2.0k | 修 `mem_stage.sv` LB/LH lane 选择 |
| 16 | tester-03 | 3.7s | — | **pass**，Verified level L0 |

最终指标：area **41122.4125**（gscl45nm），power **9.55 mW**（internal 7.15 / switching 2.23 / leakage 0.168）。

---

## 12. 文件索引（改代码前先定位）

| 想改什么 | 去这里 |
| --- | --- |
| 流程顺序 / 重试 | `orchestrator.py:431-458` |
| 续跑逻辑 | `orchestrator.py:44-115, 333-420` |
| system prompt | `subagents/common.py`（Parser/Planner/Modifier）、`model/prompts.py`（RTL） |
| user prompt 拼装 | 各 `subagents/*.py` 的 `run()` |
| JSON 校验 | `common.py:121-219` |
| 失败反馈文本 | `common.py:226-302` |
| handoff/artifact | `subagents/base.py:19-275` |
| 图校验/设计变体 | `runs.py:61-297, 861-973` |
| iverilog/vvp | `rtl/runner.py:296-421` |
| yosys/sta | `rtl/metrics.py:24-201` |
| HTTP/作业/暂停 | `web/server.py:223-435, 805-900` |
| API key | `api_key.py` |
| 项目与档位 | `agent/projects.py` |

---

**给 Codex 的建议起点**：先读 `orchestrator.py` 的 `run_agent`（200 行左右）和 `subagents/base.py`（275 行），这两处理解了，剩下五个 agent 都是"读 artifact → 拼 prompt → 校验输出 → 写 handoff"的同一模式。调试时优先用 §0 的 curl 无界面方式复现，比点网页省时间。
