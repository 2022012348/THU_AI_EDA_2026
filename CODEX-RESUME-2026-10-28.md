> 本轮已在Codex额度85%时暂停；当前唯一交接入口为 [CODEX-CURRENT.md](CODEX-CURRENT.md)。下文是过程记录。

# Codex 接手进度（2026-10-28）

已阅读 `CODEX-HANDOFF-2026-10-28-NIGHT.md`，以实际报告核实，文档中的推断不当作已证明事实。原目标继续：改进 Agent，让 L1 自主稳定通过；禁止手工修改生成 RTL、教师文件、使用参考种子。

## 已核实

- 原最好运行 `agent-20261028T120731264745-e823d5bd43ba4f6e9c373e38f5fa9b16/tester-03` 40 条失败，非完整通过。
- 接手时 79 项离线测试通过，教师目录 Git 状态为空，无遗留付费 CLI。
- 接手时 Codex 五小时额度 2% 已用；继续监控，临近耗尽暂停并交接。

## 本轮工具变化

- 新增只读 `ai_eda/agent/skills/data_bus_observer.py`，单独重放未修改的教师 TB 和不可变 RTL，按测试统计外部数据总线有效握手、退休 load/store opcode，并保留前12笔事务。无验收 verdict，不改 DUT/TB 信号。
- Tester 在仿真失败时自动调用；反馈只选失败测试（最多6个），控制 token。
- 修正反馈里“相邻 PC 重复一定是重复退休”的过强结论；合法循环也可能出现这种现象。
- 新增离线 fixture 验证握手等待、测试分组、输入不变、无 passed 结论。当前80项通过。

## 新证据

`runs/analysis/data-bus-handoff-check/result.json` 来自原最好快照的零模型费用取证。
`t08_store_fwd` 确实出现 `we=1 addr=00000200 wdata=000007ab be=1111` 的外部写握手。因此夜间交接中“store 根本没写进存储器”不能直接当成根因。需要模型根据自动证据定位数据、消费时序和流水状态，不能人工改 RTL 或注入手写诊断。

## 当前实验（接手后第一批）

运行 `agent-20261028T124412728862-4614edcbd21643008cd5e25690148489`。
从上述最好运行 tester-03 重测，`resume_retest_checkpoint=True,use_l1_reference=False,thinking=False,max_calls=4,max_repair_attempts=2`。这只是调试，不计稳定独立验收。
CLI `/tmp/eda-codex-resume.py`，输出 `/tmp/eda-codex-resume.log`。请先核实进程和最终结果再启动其他付费运行。

## 用户讨论后恢复：Tester ↔ Modifier 的修复协议

用户要求先思考架构后明确继续目标。新增的实际控制机制：

- `ai_eda/agent/repair_control.py`：不凭报错数量单独决策。新的停机超时、原先非失败测试变失败、suite 覆盖丢失或原通过suite退化，拒绝补丁；无可验证改善也不叠加补丁。恢复之前不可变的模型生成快照（不手写 RTL），保存原候选与原报告。连续两轮拒绝后结束当前批，要求重新诊断。
- `orchestrator.py`：落盘 `repair_evaluation_attemptN.json`；最终 `result.json.selected_report` 明确所保留的报告；默认续跑应恢复被保留的 checkpoint，而非最后被拒绝候选。
- Modifier 可以先返回 `request_observation` 而不返回补丁。Tester 按当前快照回答，模型再据此返回 edits。一轮最多一次问题，仍受总调用次数限制。请求/答复/快照哈希以及 `repair_contract_attemptN.json`（假设、预测、风险）留痕。
- Reviewer 同样可选择 DUT 内部信号。`skills/signal_probe.py` 只接受最多10个受限信号路径和可选单信号trigger，运行时生成只读采样器；不接受模型生成的Verilog，不改变老师TB与DUT。独立重放的提前结束绝不计验收。
- 已去掉 Reviewer 分支重复完整 Spec/Plan 的输入；Icarus constant-select sensitivity 警告不再被prompt误称为编译失败。
- 上一批 `agent-20261028T124412728862-4614edcbd21643008cd5e25690148489` 最后56条失败。中间40→37实为部分程序从结果错变为无法停机，**不能算改善**。新控制器对真实报告离线回放能识别并拒绝。

当前实验：`agent-20261028T132453496461-b0bbd1189a1a4c08bd9a489664926fc8`，CLI `/tmp/eda-codex-dialogue.py`，日志 `/tmp/eda-codex-dialogue.log`，最多4次调用/2轮修复，源为原最好运行tester-03。诊断续跑不计独立验收。

本批 Reviewer 请求 `t06_load_store` 的 `dut.ex_redirect_valid` 触发采样，重放无样本（trigger未触发），没有把空结果当作证实。下一版probe已增加前8拍样本和trigger统计，避免无触发时整份证据为空；该变化不会进入已加载旧模块的当前进程，下一批生效。

第二批交互实验已结束：40→38→38，最终未通过。`repair_evaluation_attempt2.json` 接受首个icache补丁（未出现新失败测试/新增halt超时/覆盖退化）；`repair_evaluation_attempt3.json` 拒绝无改善的第二个mem_stage补丁，并实际回退到tester-02快照。第二轮Modifier主动申请48拍IF内部采样，收到真实样本后撤回部分IF猜测，但数据通路补丁没有带来已验证改善。保留的38条仍非通过。

已开始一批全新独立生成（不续跑、不参考种子、不人工诊断），脚本 `/tmp/eda-codex-fresh.py`、日志 `/tmp/eda-codex-fresh.log`。参数：`max_calls=10,max_repair_attempts=3,max_tokens=32000,thinking=False,use_l1_reference=False`。同版本若最终通过，后续仍需另外两次相同参数全新通过才满足稳定性。接手时先检查进程再启动任务。

首个新架构全新运行 `agent-20261028T133053635791-5d48128de3d74346a286623f522f9cca` 已结束，未通过。调用9次。先修复编译缺失clk端口；第一次仿真23条失败主要为停机超时，Modifier申请真实内部采样，发现缓存握手后修复，更多测试开始执行，失败122条但不完整测试数下降，控制器保留。最终候选仍122条无改善，回退，`result.json.selected_report=tester-03/test_report.json`。不要单看23→122判断退化，观察完成性和具体失败。

又加入：
- 调用预算达到上限时保留已测checkpoint并正常结束本批，`ModelCallBudgetExceeded` 区分预算与补丁无效。
- 独立的生成前协议审查（Planner `_review_protocol`，同模型独立上下文）：只看Spec/Plan，检查逐级token消费、stall时老指令排空、ECALL与旧访存、架构值真实来源和握手。模型可修订完整notes及内部端口合同，禁止改顶层/模块/文件名，禁止输出RTL。落盘 `plan_draft.json` 与 `plan_protocol_review.json`，Coder接收审查后计划。
- 当前89项离线回归通过。

正在第二次全新运行：脚本 `/tmp/eda-codex-reviewed-fresh.py`、日志 `/tmp/eda-codex-reviewed-fresh.log`。最多12次调用、4轮修复、max_tokens32000、thinkingFalse、无参考/续跑/人工证据。先检查实际进程和报告再继续。

第二次全新运行 `agent-20261028T134034958696-522d084547f644d1ba85bcfe297032d8` 在协议审查输出达到7000 token上限时中止，尚未产生RTL。截断输出未被采纳。改进审查为最多8个精确文本片段修改（notes或内部接口），不再全量重写，保留未改内容；对应回归已更新，当前90项通过。

为节省费用，新增 `contract_review` 失败点恢复：复用原模型的Spec/plan_draft，仅重做审查后生成，不重付Parser/Planner。这是诊断续跑，不计全新验收。
现在正在运行 `/tmp/eda-codex-contract-resume.py`，日志 `/tmp/eda-codex-contract-resume.log`，源是上述截断的审查运行，最多10次调用/4轮修复。当前Codex五小时额度24%已用。
