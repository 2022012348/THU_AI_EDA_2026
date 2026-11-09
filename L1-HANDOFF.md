# EDA Agent · L1 工作交接

## 2026-10-28 最新结果

用户已要求继续。L1 的模型生成路线现已通过原始教师 TB 和当前两组独立定向检查；2026-10-27 的暂停状态和“纯模型尚未通过”是下文历史记录，已过时。

最终验证运行：`runs/agent/agent-20261028T024203355757-79183018931a49d080146e77c57c66d8/`。这是对 `agent-20261028T023835687208-8da3619ed12845a08fc37062bb41613c` 的 Tester 第 2 轮不可变快照重新测试，不使用参考 RTL。RTL 起始于模型生成，并经过多轮 Modifier 修复；修复过程中 Codex 提供过经独立定向测试、按文件 SHA-256 校验的诊断证据，因此它是**模型生成和模型修复、人工/Agent 定向诊断辅助**，不应宣称完全无人干预的零基础一次成功。历史 manifest 的部分来源字段为 unknown，但原始 Coder 事件、各轮快照和续跑链可追溯。

- 老师的 TB 未改动；`git status --short -- content/tasks/homework_rv32i5` 无输出。原教师 L1 TB base 291512、cache 2432、performance correctness 47800 项检查通过；L2/L3 的 predictor/ooo suite 按预期跳过。
- 独立探针位于 `content/agent/verification/`，不属于老师 TB。两项均通过：I-Cache 最后 refill 同拍 flush、旧行保留和错误路径行不命中；ID/hazard 的 MEM 等待保持、load-use 气泡、redirect 同拍、IF 请求稳定和 ECALL 单次推进。其覆盖范围有限，不等于证明所有规格边界。
- 本次 verified L1；gscl45nm 面积 138027.7002；OpenSTA/VCD 估算功耗 0.032 W。以该运行 `tester-01/test_report.json` 为准。
- 最近离线回归 `.venv/bin/python -m unittest discover -s checks -q`：62 项通过；`git diff --check` 和前端 JS 语法检查通过。
- Tester 与手动 Retest 在 L1 模式同时运行独立探针，报告中的 `teacher_passed` 保留教师结果；ID/hazard 架构无法识别时标记 `not_covered`，不应误称该项通过。已覆盖过的控制探针不会因后续接口变化悄悄退化为跳过。
- 新增通过哈希校验的诊断证据 handoff、精确文本替换回退、内部端口契约更新、按失败轮次恢复和先重测历史快照的功能；`resume_retest_checkpoint=True` 需与 `resume_tester_attempt` 一起提供。网页运行配置也有对应的历史轮次与先重测选项。
- 初始独立人工定向修复并通过教师 TB 的实验仍保存在 `runs/analysis/l1-model-assisted-20261028/`，与最终 Modifier 修复结果区分。额外证据和探针保存在 `runs/analysis/`；旧的某些试验因手动 SIGINT 可能仍显示 running，不代表后台进程仍在运行。
- 代码仍在本地工作树，未提交或推送。先前启动的网页服务可能仍使用旧版本；使用新界面前需用户允许的常规方式重启该服务。

---

更新时间：2026-10-27（北京时间）。当前任务应保持暂停，等用户回来明确要求继续后再运行，不要自行启动模型调用或自动化。

## 用户目标与当前状态

用户希望通过改良多 Agent 架构、prompt、模型调用等方式迭代跑通 RV32I L1。用户临时要求停下并留好 MD 交接，后续大约一点多回来继续。此处“一点多”没有具体日期和提醒要求，不要据此创建定时任务。

实际代码仓库：`/Users/abel/THU_AI_EDA_2026`。聊天目录 `/Users/abel/Documents/ChatGPT/EDA_AGENT` 是另一个空 Git 仓库。原始 DeepSeek 文档是仓库内未跟踪的 `AGENT-DEBUG.md`，不要覆盖或删除；架构分析和阶段性记录在 `ARCHITECTURE-REVIEW.md`。

**参考实现模式已通过 L1；纯模型生成模式尚未通过。** 不能将参考 RTL 的成功描述成模型从零生成 L1 成功。工具现有两种模式：网页 Run configuration 中勾选 `L1: use reference RTL` 为参考模式（默认），取消勾选为纯模型模式；Python `run_agent(..., use_l1_reference=True/False)` 也可选择。

## 已完成的代码工作

- L1 参考工程按完整的 11 个模块加载，包含 `alu.sv`，不与模型模块混搭；Planner 从参考 RTL 实际端口生成计划，避免此前规划接口与实际参考文件不一致，也节省一轮未使用的模型调用。
- 修改参考 `icache.sv`，丢弃错误路径 refill，处理 flush/ready 同拍与等待期间请求稳定；在 `rv32i5.sv` 的 IF→I-cache 请求路径加入单项缓冲与控制流门控，避免 IF stall 撤销未接受请求，也避免热循环中的错误路径外存请求超过教师 TB 阈值。
- 修正 prompt 中与 L1 Spec 冲突的 no-write-allocate 和错误路径安装建议，补充握手、指令获取、ECALL、Icarus 动态索引等约束。
- 各轮 RTL manifest 引用不可变快照；续跑读取上次实际测试的 RTL 和有效 plan，校验项目与已知参考模式，保留简短失败诊断；manifest 记录模型/参考来源和后续模型修复。
- 诊断包涵盖重复失败、分测试 trace、完整关键编译错误；模型空回答有限重试并计入调用预算，截断回答拒绝执行；运行 ID 增加 UUID 防止并发碰撞。
- 上一轮任务已有的源码修缮也在工作树中。所有这些更改仍未提交或推送；不要重置、覆盖或清理这些用户数据。

## 验证与证据

最近的参考模式完整端到端运行：

- `runs/agent/agent-20261027T155148968706-b472487a33284001a2f9606a0cdc33ad/`
- 第一次 Tester 通过，verified CPU level L1；base、cache、performance_correctness 三组通过，L2/L3 专属测试按预期跳过。
- 该运行面积 138598.369（gscl45nm library area units），OpenSTA 功耗估计 0.011 W。具体以该运行 `result.json` 为准。
- 一次前序参考模式运行 `agent-20261027T153830370344` 也首轮通过。定向 Icarus 验证覆盖错误路径 refill、ready 等待、同拍 flush、已有缓存行和 IF stall。
- 最近一次离线回归：`.venv/bin/python -m unittest discover -s checks -q`，29 项通过；`git diff --check` 通过。Web 首页和 `/js/agent-runs.js` 在临时本地端口 HTTP 200，包含 L1 模式选择；Node 的语法检查通过（可用 `/Users/abel/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check ai_eda/web/static/js/agent-runs.js`）。

纯模型实验：

1. 初始 `agent-20261027T152856648100` 经 8 轮修复仍未通过，仿真有大范围错误。
2. 改进提示后的 `agent-20261027T153902968736-ed50c33de09f426b824e1a2f823c1749` 首轮有 Icarus 编译错误，经修复进入仿真，多个测试等待 halted 超时；Modifier 返回空补丁而停止。
3. 续跑 `agent-20261027T154609415302-0d7e67438f184c4ca563636fc6b2c182` 和 `agent-20261027T155006744612-7ff983f84da44745a8ba04fc687f7ba6` 仍失败，终止于 Modifier 多次空补丁。
4. 最后一次针对性续跑 `agent-20261027T155229657157-19e0604fef074fdf898b369ed24542f8` 正在 Modifier 调模型时，收到用户暂停要求；已对该进程发送 SIGINT，确认进程退出。由于 `KeyboardInterrupt` 不走当前 AgentCancelled 处理，`events.json` 最后一条仍显示 `running`，这是已中断的磁盘快照，**不表示进程还在运行**。该目录内的 Tester→Modifier handoff 与输入 RTL 快照仍在，可以从此 run 续跑。尚未产生该次 Modifier 的完整结果，不要认定通过或失败。

### 已确认的纯模型 RTL 故障

对 `agent-20261027T154609415302-0d7e67438f184c4ca563636fc6b2c182` 的 tester-04 快照进行了隔离 Icarus 验证：

1. I-cache cold miss 的 refill 完成后，无论最初请求的 word offset，均返回最后一拍的 `mem_resp_data`（word3）。定向测试中请求 word0，实测得到 word3。应锁存请求 offset：word0–2 取已经保存的 refill 数据，word3 取当拍数据。该问题可解释部分 retire PC/指令不一致。
2. hazard 单元在 ID 识别 ECALL 时同拍拉高 `id_stall`；ID 的 stall 分支清除 `id_ex_valid/id_ex_ecall`，而 halt_pending 期间仍持续 stall。定向仿真验证 ECALL 无法进入 EX；应在无更老冲刷且下游可接收时让 ECALL 恰好进入 EX 一次，只冻结更年轻取指。该问题是停机超时的一个明确原因。
3. 待验证：MEM 请求已发出后，`req_pending=1` 似乎会解除 `mem_stall`，可能在响应前推进流水线；此项目前是代码审阅疑点，尚未证明是根因。
4. 周期级观察到 IF 在第一次请求尚未响应时再次提出相同地址，说明请求状态还需检查；不能仅凭这一观察断言所有失败由它造成。

上述两条通用检查已加入当前 Modifier/Coder prompt；最后一次续跑正使用这些提示，但在取得完整响应前被用户要求中断。

## 用户回来后建议的继续步骤

1. 先确认用户希望继续当前会话和是否优先追求纯模型生成；参考模式已通过。不要因为此文档本身而自行启动工作。
2. 检查最新源码与工作树：`cd /Users/abel/THU_AI_EDA_2026 && git status --short`，保留所有未提交修改及未跟踪文档。`runs/` 是本机运行记录，通常被 `.gitignore` 排除，注意保留。
3. 检查中断运行快照及 handoff，必要时从 `agent-20261027T155229657157-19e0604fef074fdf898b369ed24542f8` 的 Modifier 续跑，必须使用 `project_id='rv32i5_cache'` 和 `use_l1_reference=False`。示例（会调用付费模型，只在用户要求继续后使用）：

   ```python
   from ai_eda.agent.orchestrator import run_agent
   result = run_agent(
       project_id="rv32i5_cache",
       use_l1_reference=False,
       resume_from="agent-20261027T155229657157-19e0604fef074fdf898b369ed24542f8",
       max_repair_attempts=8,
   )
   ```

4. 若 Modifier 仍重复空补丁，不要无限重复同一模型调用。应根据上述已验证信号构造可重复的小测试与结构化反馈，检查真实 RTL 修改，再运行完整教师 TB；报告自主生成和参考模式的结果。
5. 当前本机还有此前启动的 `ai_eda serve` 进程，非本次生成运行；它可能加载了旧源码。用户要使用网页时应先确认服务状态并按需要重启，避免擅自结束用户进程。

## 文件与安全注意

- 主要源码变更涉及 `ai_eda/agent/`、`ai_eda/model/client.py`、`ai_eda/web/`、`content/agent/skills/rv32i5_l1_reference/`；新增离线测试在 `checks/`。
- `.api_key`、`.venv/`、`.tools/`、运行记录均是本机资源；不要读取或打印密钥，也不要提交或删除它们。
- 保持 handoff schema v1、旧记录的读取兼容及教师 TB 本身；不要为通过而放宽测试或改验收。
