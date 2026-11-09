> 当前状态已更新：请先读 [CODEX-CURRENT.md](CODEX-CURRENT.md)。下文包含早先暂停与历史记录，不能直接按旧命令恢复。

# DeepSeek harness 接手：让 EDA Agent 独立、稳定通过 L1

更新日期：2026-10-28，北京时间。本文是用户要求准备的交接任务书，状态和进程必须在接手时重新核实。

## 暂停时最终更新：Codex 额度 89%，可交给 DeepSeek harness

用户要求额度快耗尽时写 MD，供其 DeepSeek harness 继续。当前 Codex 工作在此暂停；截至暂停已检查无 `run_agent` CLI 进程，当前没有需要等候的付费运行。用户没有撤销原目标，接手 harness 可在用户交接本文后继续按下述边界推进。

最新完整正式测试仍是 `agent-20261028T082402594012-fb6b4b5f9e7649d886a0bf532d831ef9/tester-04/test_report.json`，原教师 TB 未通过。生成 RTL 没有手工编辑，老师目录的 Git 状态无改动。最新离线回归 **79 项通过**，`git diff --check` 通过。

暂停前又完成两项无需模型费用的自动诊断改进，**尚未被完整的生成/修复验收运行验证**：

1. `content/agent/verification/icache_flush_edge_tb.sv` 现在先检查四种 cold-miss word offset、十六次 cached-word 读取，再执行原有 flush 边界检查。工具返回已执行通过项的明确 scope；`report_feedback` 同时把通过和失败证据交给 Modifier，避免模型忽略反证。在最新不可变快照上重放，word-offset 检查通过，旧行保留检查失败。工具日志在 `runs/analysis/l1-offset-tool-replay/`。这是自动工具观察，不代表整个 I-Cache/IF 通过。
2. `ai_eda/agent/skills/retirement_observer.py` 是独立只读观察重放：保持原教师 TB 与 DUT 完全不变，额外观察其固定调试接口与教师当前指令内存，只取最早五个错配。诊断重放提前结束只为限量取证，**绝不能当成正式教师测试通过**。Tester 在实际报告出现 retire mismatch 时自动调用，将 `retirement_observation` 交给 Modifier。最新快照实际观察到 PC=`00000004`、insn=`20000093`、expected=`00408093`，以及 PC=`00000008`、insn=`00408093`、expected=`0010a023`；见 `runs/analysis/retirement-observer-tool-check/`。这些只证明 PC/指令错配，不足以证明具体根因。不要直接手工修 RTL，也不要把人工写的根因塞给模型。

独立 Reviewer 曾把 refill 前几拍已经写入的 word0/1/2 误判为最后一拍仍读旧值。不要继续盲目相信这条诊断；应让新版 Tester 自动提供 word-offset 反证和真实 retire 错配，再由模型自行分析。

**接手第一步推荐小批次调试**：先用新版 Tester 重测最新 tester-04 快照，让新观察器自动进入正式修复反馈；最多 3 次模型调用、1 轮修复。以下不是从零稳定性验收，成功后仍须另做全新独立运行：

```sh
cd /Users/abel/THU_AI_EDA_2026
.venv/bin/python -u - <<'PY'
import json, signal, threading
from ai_eda.agent.orchestrator import run_agent
cancel = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: cancel.set())
def progress(e):
    if not e.get('streaming'):
        print(json.dumps({k:e.get(k) for k in ('run_id','node_id','status','call_index','output_tokens')}, ensure_ascii=False), flush=True)
r = run_agent(project_id='rv32i5_cache', use_l1_reference=False, thinking=False,
              resume_from='agent-20261028T082402594012-fb6b4b5f9e7649d886a0bf532d831ef9',
              resume_tester_attempt=4, resume_retest_checkpoint=True,
              max_calls=3, max_repair_attempts=1, cancel_event=cancel, on_event=progress)
print(json.dumps({'run_id':r['run_id'],'status':r['status']}, ensure_ascii=False))
PY
```

如果这一轮没有带来实际改善，先检查模型是否读到新证据、补丁是否对应其假设，以及下一步缺哪种观测；不要循环照抄同一续跑命令。

## 用户目标和不可越过的边界

用户原话：通过改良多 Agent 架构、prompt、模型调用，使 Agent 在独立运行的情况下稳定跑通 L1，不得单独修改 RTL 等作弊。用户特别强调不得修改老师的 TB，并要求节约 DeepSeek token。

你接手的是“改进生成工具”的工作。允许修改 `ai_eda/` 的调度、模型调用、提示词、自动诊断、协议校验，以及对应离线回归。生成的 RTL 只能由项目内部 Coder/Modifier 模型产生或通过它们返回的补丁应用。不要由接手 harness 手工改写运行产物或参考 RTL 来获得通过；也不要向验收运行注入手工针对某个快照写的诊断答案。通用工具自动收集证据、独立模型自动诊断可以使用。

禁止修改 `content/tasks/homework_rv32i5/` 的任何教师文件、放宽门槛、伪造退休/能力事件、按测试地址或程序硬编码。独立实验必须 `use_l1_reference=False`，禁止将已有通过 RTL 或参考 RTL 作为种子。原先 L1 的历史成功有人工诊断/参考实现介入，不能计为自主稳定通过。

“稳定”至少用同一版本工具、同一参数的 3 次全新独立运行连续通过来证明。每次都从原 Spec 开始，无 `resume_from`，无 `diagnostic_evidence`；保留完整原始教师结果和模型来源。续跑可以用于调试工具，但即使续跑通过，也不能替代这些独立验收。当前尚无这样的通过证据。

## 仓库、服务与密钥

- 实际仓库：`/Users/abel/THU_AI_EDA_2026`。聊天工作目录 `/Users/abel/Documents/ChatGPT/EDA_AGENT` 是另一个仓库，勿混用。
- Python：仓库内 `.venv/bin/python`。本机有 `iverilog`、`vvp`、`yosys`；模型调用需要网络。不要重建环境、重置工作树、删除运行记录或覆盖未提交更改。
- 当前服务商：`https://llmapi.paratera.com/v1`；模型 ID：`DeepSeek-V4.1-Flash-1017`。已通过 models 列表精确核对和最小流式 OK 测试，曾有请求超时，不能假设网络始终正常。
- 项目客户端：`ai_eda/model/client.py`；Key 由 `ai_eda/api_key.py` 从本地 `.api_key` 读取。不要展示、提交、打印或把密钥复制到 MD/命令行参数/日志。备份在忽略目录 `runs/local_api_profiles/`，也不要输出它们的内容。
- 工作台：`http://127.0.0.1:8003/`。其他旧端口服务可能加载旧代码/旧服务商，不要用旧页面启动付费运行。网页是可选工具，Python 路径足以完成任务。

## 当前实验状态：本批已结束，未通过

最近完成的实验：

`runs/agent/agent-20261028T082402594012-fb6b4b5f9e7649d886a0bf532d831ef9/`

它是同一自主生成链的调试续跑：从 `agent-20261028T075837501153-17253d3a1a104075815d3b4580f7b5ea` 的 Tester 第 4 轮不可变快照重新测试，再由模型修复。未使用参考实现，无手工 RTL 修改或人工诊断注入。不是新的稳定性验收样本。

本次限额：最多 6 次模型调用、3 轮修复；`thinking=False`。本批已运行完毕，6 次调用已用，最终 tester-04 的原始教师 TB 仍失败（非墙钟超时）。进程已退出，退出码 0 只表示工具正常结束，**不表示 CPU 通过**；运行终态为 failed。日志：`/tmp/eda-l1-paratera-bounded-report.log`。仍有退休 PC/指令不匹配、exit_code 和 Cache 边界失败。不要把这些现象直接当成已证明根因；也不要立即无限续跑同一修复策略。

旧本机进程 PID 为 `40819`，已退出；PID 会被复用，**不要依据旧 PID kill**。接手时先检查是否已有用户启动的新实验：

```sh
cd /Users/abel/THU_AI_EDA_2026
ps -Ao pid,etime,command | rg '[r]un_agent'
tail -n 8 /tmp/eda-l1-paratera-bounded-report.log
git status --short -- content/tasks/homework_rv32i5
```

只有命令行与目标运行相符、进程实际存活时，才将它认作在运行。不要仅凭 `events.json` 的 running 状态启动重复任务：早先 SIGINT 的旧运行可能保留 running 字段，但其进程已经退出。先让当前实验结束或按用户暂停要求停止，禁止并发付费实验。

上一轮 `agent-20261028T075837501153-17253d3a1a104075815d3b4580f7b5ea` 因日志状态膨胀到约 360 MB，每秒重复序列化导致 CPU 近满载，已明确 SIGINT 停止。不要再观察该旧进程或重启旧代码。

## 已完成的 Agent 改进

1. Planner 检测同模块重复端口，要求模型修正；CPU 规划 prompt 明确流水寄存器所有者、hold/bubble/flush、前递/写回编码和请求生命周期。
2. CPU Coder 联合生成整个项目 JSON，以共享跨模块实现上下文；校验所有计划文件和模块头后才写入；来源 manifest 记为 model。没有复制参考 RTL。
3. Modifier 优先输出 `edits`（唯一匹配的 before/after），机器校验后应用；完整文件兼容仍保留。新接口非法时反馈给模型重试，内部旧接口非法不应阻止合法修复，顶层外部接口禁止变更。
4. 每轮只向 Modifier 提供完整冻结合同、当前快照、最新证据与上轮修复摘要，不重复发送整个旧快照/补丁历史。固定合同放在稳定前缀，以减少重复输入和促进支持方的前缀缓存。
5. Tester→Modifier 的 `repair_effect_attempt*.json` 区分新增、仍存在、不再报告的失败；超时/编译失败时，不把未执行的检查误称为修好。
6. 重复失败时，用独立模型上下文做 reviewer，只读当前快照与报告，诊断自动保存哈希。模型诊断是建议，不能称为经过仿真证明；不得给 Reviewer 手工注入答案。
7. 增加只读 Yosys `hierarchy/proc/flatten/check` 结构证据，保存日志，不改变教师结果或单独以静态无警告宣称通过。
8. **重要修复：**旧 `test_rtl` 在仿真超时时把 stdout 中已输出的 checks/trace 丢弃。现在保留有界轨迹样本、按名称/详情合并的失败计数，并将完整 stdout 单独写入 `simulation_stdout.log`。完成的超大输出也压缩诊断字段，但能力、测试组和性能结论仍从完整输出解析。超时永远不是通过。
9. 最新运行的状态文件约 300 KB，已保留 82 万余次失败的合并计数和各测试关键轨迹，避免重现 360 MB 状态文件反复写入的问题。
10. 每次调用写 `model_usage.jsonl`，包括格式恢复和空响应重试；服务端未给 usage 时明确标估算。SDK 隐式重试关闭，网络读取超时 120 秒；不要另加无限重试。最近本地离线回归：**79 项通过**。这不证明 L1 达标。

关键代码：`ai_eda/agent/subagents/{planner,coder,tester,modifier,base,common}.py`、`ai_eda/agent/rtl_contracts.py`、`ai_eda/agent/skills/{cpu_diagnostics,rtl_structure}.py`、`ai_eda/rtl/runner.py`、`ai_eda/model/client.py`。所有改动未提交/推送；不要擅自清理其他旧修改。

## 接手后的优先步骤

1. 核实当前进程与最新完整 Tester 报告。查看 `tester-*/test_report.json`、`structural_diagnostics`、`repair_packet_attempt*.json`、`repair_effect_attempt*.json`、`independent_review_attempt*.json` 和模型原始输出。不要在 MD 内的旧现象上凭记忆修代码。
2. 若这批仍失败，先评价模型到底拿到了什么证据、补丁是否改变对应逻辑、是否反复修同一假设、是否发生回归。优先改进调度、证据筛选和模型交互，而不是盲目叠加调用或手工修产物。
3. 调试续跑可复用模型自行产生的快照，减少生成费用，但应选择明确 Tester 轮次并先重测，确认新版 Tester 的证据；不要把它记为独立验收。
4. 一次通过后冻结 Agent 版本与参数，再做从零的重复验收。每次验证原教师 TB、声明/行为验证的 L1、已有独立探针和来源 manifest。任何一次失败都意味着尚不能声称稳定完成。
5. 完成或暂停时更新本文：具体 run ID、模型/参数、终态、通过/失败证据、进程已退出的证据、下一步。不能把“离线框架测试通过”当成“CPU 通过”。

离线检查（无需模型费用）：

```sh
cd /Users/abel/THU_AI_EDA_2026
.venv/bin/python -m unittest discover -s checks -q
git diff --check
git status --short -- content/tasks/homework_rv32i5
```

## 小预算的全新自主运行命令

以下命令会消耗 API token。每批只启动一次，最多 12 次模型调用、4 轮修复；不要用自动无限重试外层套它。独立验收不填 resume 或外部诊断参数。

```sh
cd /Users/abel/THU_AI_EDA_2026
.venv/bin/python -u - <<'PY'
import json
import signal
import threading
from ai_eda.agent.orchestrator import run_agent

cancel = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: cancel.set())

def progress(event):
    if not event.get('streaming'):
        print(json.dumps({k: event.get(k) for k in
              ('run_id', 'node_id', 'status', 'call_index', 'output_tokens')},
              ensure_ascii=False), flush=True)

result = run_agent(project_id='rv32i5_cache', use_l1_reference=False,
                   thinking=False, max_calls=12, max_repair_attempts=4,
                   cancel_event=cancel, on_event=progress)
print(json.dumps({'run_id': result['run_id'], 'status': result['status']}, ensure_ascii=False))
PY
```

预算更小的调试续跑：在上述 `run_agent` 中加入 `resume_from='确切的已核实运行目录名'`、`resume_tester_attempt=已核实轮次`、`resume_retest_checkpoint=True`，并改为 `max_calls=6,max_repair_attempts=3`。不要把这里的说明字符串照抄作真实 run ID。断点报告和原始文件校验由工具处理，勿直接修改 artifact 或伪造状态。

## 暂停与额度

用户要求 Codex 额度快用完时暂停并写 MD。最近一次检查：五小时额度使用 **89%**，不是 DeepSeek 账户余额；额度会变化。Codex 已按此条件暂停，无付费 CLI 运行遗留；最新交接信息见本文开头。

外部 DeepSeek harness 不应假设自己有 Codex 的额度工具。它应监控自己的模型调用次数和 `model_usage.jsonl`，不能把估算 token 当作服务商精确账单。若用户指定金额/次数预算，以用户预算为上限。API 失败先检查连接与已有进程，不要反复重启已在运行的任务或为相同无效修复反复付费。

---

## 2026-10-28 晚 · DeepSeek harness 接手记录（Round 1）

**结论：仍未通过，但把"测量口径"和"修复记忆"两个系统性问题修好了，失败数 72 → 40（确定性）。**

### 已完成的工具改动（全部在 `ai_eda/`，未改 RTL、未改教师 TB）

1. `agent/skills/retirement_observer.py`：失配时额外输出 `imem_addr / imem_valid / imem_ready / imem_rdata / expected_at_addr / insn_at_pc_minus4 / pc_minus4 / prev_retire / prev_if`。
2. `agent/subagents/common.py::report_feedback`：新增机械配对统计（"N 条失配，命中 pc 0 次、命中 pc-4 5 次"），并写入 `RV32I_MODIFIER_RULES` 两条通用排查顺序（先比对相邻地址；取指地址必须绑定到被消费的响应）。
3. `agent/subagents/common.py`：`MODIFIER_SYSTEM_PROMPT` 增加 iverilog 工具链限制（`always_*` 内常量段选择会报 `sorry: constant selects ...`；枚举三目需显式转换）。这是模型连续两轮踩同一个坑的根因。
4. `agent/orchestrator.py::_carry_modifier_memory`：续跑时把上游运行的 `notes / failure_fingerprint / failing_tests` 带进新运行——之前续跑 Modifier 上下文是空的，模型会重复上一轮已经失败的补丁。
5. `agent/subagents/modifier.py::_syntax_error`：补丁落地前用 `iverilog -g2012 -t null` 做一次解析检查，坏补丁当场退回重试，不再白占一轮 Tester。
6. `agent/projects.py`：rv32i5 四档 `timeout_seconds: 120`。**这份 TB 完整仿真约 24 s，原先 20 s 墙钟会中途杀仿真**，导致同一份 RTL 得到 36/24/52 这种飘忽的 check 数——之前多轮"退化"其实是测量假象。功能超时仍由 TB 内部 500 周期等待判定。

### 关键证据（已闭环）

退休 PC 与指令错位一个 4 字节字：`pc=4 / insn=20000093 / imem[4]=00408093 / imem[0]=20000093`，5/5 命中 `imem[pc-4]`。模型据此自行改对 `if_stage`（拆分 `pc_fetch` 与 `if_pc_r`），失配归零。

### 当前状态

- 最新运行：`agent-20261028T120731264745-e823d5bd43ba4f6e9c373e38f5fa9b16`，连续三轮 **40 条**失败（确定性）。
- 剩余失败：halt 超时（`t06_load_store`、`t09_branch`、`t10_jump`、`t13_dft`，PC 卡在 0x29ac / 0xec / 0x80）、`t08_store_fwd` x5=0xa5a5a5a5、`t06b_neg_imm` x2=0、`t11_halt` x10=0、探针 `l1_icache_old_line_preserved`。
- 离线回归：79 项通过。`content/tasks/homework_rv32i5/` 零改动。

### 下一步建议

用工具补一条"超时前最后 N 条退休 PC/指令"的证据（现在只有 500 周期超时和固定 imem_addr，模型看不到循环体），再跑小批次；单纯重复现有证据已经三轮无变化。

### Round 2 追加（同一晚）

新增两个通用能力，离线回归仍 79 项通过：

7. `agent/skills/retire_tail.py`：只读"退休尾部"探针，环形缓冲 48 条，在 `final` 块一次性打印；Tester 在出现 `等待 halted 超时` 时自动调用。**首次运行就抓到：总退休数 670218，且相邻 PC 成对重复（`pc x2`）——每条指令退休了两次。**
8. `report_feedback`：把尾部证据压成一行（total/halted/exit/last_test + 最近 PC 序列），并提示"相邻 PC 重复 = 重复退休，长块重复 = 死循环"。
9. `modifier.py::_failure_digest`：把失败按出现次数排序的小表**放到 prompt 最前面**（之前 20k+ Spec 在前、失败摘要在最后，模型容易被带偏）。

本批结果：40 → 41 条，**未改善**。模型连续两轮仍把补丁打在 `if_stage/icache`，而最高频失败是 `t08_store_fwd`（11 次，`x5 期望 0x7ab 得到 0xa5a5a5a5` = 存储压根没写进存储器）与 `t06b_neg_imm`（5 次，load 读回 0）。

**下一轮结论**：需要一条针对 D 通路的定向探针（参照 `l1_icache_probe.py` 的黑盒模式，直接例化 `dcache/mem_stage` 并打印 `dmem_valid/we/addr/wdata/be` 与回读值），否则模型会一直在 IF 层打转。单纯加文字提示已证明无效。
