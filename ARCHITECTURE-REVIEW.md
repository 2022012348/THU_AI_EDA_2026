# EDA Agent 架构核对与修缮记录

日期：2026-10-27。依据：`AGENT-DEBUG.md`、当前源码、保存的 RV32I L0 三轮运行报告。

## 项目实际在做什么

这是面向数字电路设计作业的自动化工作台：冻结设计规格，规划模块与接口，逐文件生成 SystemVerilog，运行固定教师 TB，失败后自动修复，再评估面积与功耗。支持 stream_filter FIFO 和 RV32I L0–L3。

执行链为 `Parser → Planner → Coder → Tester ⇄ Modifier`。这是有角色分工和文件交接的固定流水线：Tester 是确定性的 Python/EDA 工具调用，其余四个角色使用模型。流程图用于展示，编辑设计变体不会改变执行顺序。当前修缮继续使用这套模型，未将界面图解释为可执行工作流。

本地实际代码库为 `/Users/abel/THU_AI_EDA_2026`，origin 为 `2022012348/THU_AI_EDA_2026`；聊天工作目录 `/Users/abel/Documents/ChatGPT/EDA_AGENT` 当时是空 Git 仓库。

## 本次已实现

- **反馈证据**：带 test 标签的 expected/actual 差异仅从失败测试取；无 test 标签时要求明确的 `actual_*` / `out_*` 字段。保留实际值为 0 的差异。
- **超时诊断**：只在 simulation 中至少两项、且多数检查属于 halt 超时时生成一段诊断；不再无依据地声称 PC 一直变化，也不把超时直接等同于 ECALL 故障。
- **确定性诊断接线**：RV32I Modifier 每轮保存 `artifacts/repair_packet_attemptN.json`，包括分组失败、失败测试的首尾 trace、失败指纹、粗粒度分数。连续指纹相同时提示重新分析根因。分数不参与通过判定或自动回退，教师 TB 仍是验收来源。
- **档位上下文接线**：Planner、Coder、Modifier 接入已有 L1–L3 契约辅助函数。冻结 Spec 在冲突时优先；seed 条件只描述提供 seed 时的资格，不代表当前调度器会自动加载低档位运行。
- **项目提示隔离**：RV32I 修复规则、checklist、代码模式只加入 RV32I Modifier，不再进入 FIFO 的 system prompt。
- **接口与规格完整性**：不再将 `interfaces` 截断到 1000 字符；纠正 Planner 中要求连接两端“同方向”的提示，明确 output 对 input；Modifier 首轮读取完整 Spec，避免截掉末尾验收条件。
- **可恢复身份**：Coder 事件记录 `module`、`file`、`implementation`，续跑优先读取结构化模块名，兼容旧标题；递归恢复 `rtl/` 子目录；将 `waiting_input` 纳入恢复点识别。该项不意味着恢复了尚未提交的人在环回答。
- 删除无人使用的 `MAX_TEST_ATTEMPTS`，重试上限仍以调度器参数为准。

handoff schema v1、既有文件命名、报告验收逻辑、教师 TB 均保持兼容。新增 repair packet 是普通 artifact，不要求旧 handoff 提供它。

## 对 DeepSeek 文档的核实与纠正

B1 不能照单全收。保存的 tester-01 中，DFT 的 `mag=-1263225674` 不只是参考信息：`checks` 明确包含 `t13_dft` 的 DMEM 数据和频点幅值失败。因此这些差异应保留。筛选未失败测试能降低噪声，但不会把这批真实 DFT 失败移除，也不能声称这次已证明模型修复质量提高。

文档“Tester 轮次范围 1–10”也不准确：源码接受 `max_repair_attempts=1..10`，实际 Tester 上限为 2..11，默认 9。

L1 Coder 存在直接写入参考 RTL 的旁路。评估“自主生成能力”时应区分参考实现和模型生成；本次通过事件的 `implementation` 字段显式记录，未改变现有旁路行为。

## 验证结果

离线回归命令：

```sh
.venv/bin/python -m unittest discover -s checks -v
```

9 项通过。包含真实 orchestration / artifact / handoff / 流式消费代码配合模拟模型和模拟 Tester，验证 FIFO、L0、L2 的两次失败再通过，重复失败指纹，档位上下文传递，嵌套 RTL 恢复、旧标题兼容、等待输入恢复点、完整接口和长 Spec。测试不调用 API，临时运行目录自动清理。

此外，使用保存的 `agent-20261027T080948039158/artifacts/generated_attempt3.sv` 在临时目录重跑真实工具链：

- 教师 TB 通过，verified CPU level 为 L0。
- Yosys / gscl45nm 面积：41122.4125。
- OpenSTA 功耗估算：0.00955 W（9.55 mW），metrics status 为 ok。

该实测证明已有 RTL 和本机工具链仍可工作；不等于验证新提示下重新生成的 RTL。尚未调用付费模型执行新生成任务，也未实测 L1–L3 新生成质量。

## 仍需单独设计的架构工作

1. **可执行编排**：若作业要求用户通过图自由组合角色，需定义节点输入/输出、允许的边、重试和恢复语义，再让执行器消费该图。只替换 while 循环不能解决接口契约问题。
2. **版本化 RTL 快照**：manifest 目前指向可变的 `project/rtl` 文件，多轮修改后旧 manifest 无法独立还原当时的多文件状态；虽然保存了合并 RTL，审计与回退仍应采用不可变快照。
3. **上下文预算**：完整 Spec 避免静默丢失要求，但增加输入长度；当前 Modifier 历史裁剪不是严格 token 预算，后续应以当前 RTL + 结构化修复摘要重建上下文。
4. **运行服务**：并发资源管理、作业重启恢复、events 全量重写和完整 report 重复保存的问题仍存在，应与前端读取协议一起改造。
5. **高档位递进**：现有 seed 资格函数并不等于自动复用已验证的 L0/L1/L2；需增加显式来源选择、契约校验与失败回退，才能评估递进生成效果。

本次代码修改保存在本地，未提交或推送 GitHub。

## 2026-10-27 L1 迭代更新

### 实现和验证

- 默认的 L1 参考模式使用完整 11 模块集合，并从参考 RTL 的实际端口生成有效计划；不再混合不兼容的模型计划和参考 RTL。Planner 在该模式无需额外模型调用。界面运行配置可关闭参考，改为纯模型生成；事件和 manifest 标注来源。
- 修正参考 I-Cache 的错误路径 refill、同拍 flush 和响应丢弃，增加 IF 请求缓冲以保持等待期间的 valid/地址稳定，并避免对未解析控制流发起新的顺序取指。新增定向 Icarus 测试验证 stale refill、ready 等待、同拍 flush、既有缓存行和 IF stall。
- RTL manifest 引用每轮不可变快照。Modifier 续跑恢复实际验证过的版本，并保留失败指纹、测试名和上次诊断摘要；不同项目或明确不同的生成模式不能混合续跑。模型流式输出为空时有限重试，截断输出保留现场但拒绝当作完整结果。
- 改正 L1 提示中与规格冲突的 cache/no-write-allocate 指示，强调 valid/ready、取指请求和响应的关联、Icarus 的动态索引限制。失败反馈保留编译错误、各失败测试附近的 trace 和跨轮持续失败的测试。
- 修复并发启动可能生成相同 run ID 的问题。编号增加随机后缀，原有记录仍可读取。

完整参考模式端到端记录 `agent-20261027T153830370344` 首轮通过，verified L1；基础测试、Cache 测试和性能正确性测试通过。用的是参考 RTL，不表示模型自主生成 L1 已通过。实际指标以该运行 `result.json` 为准。

纯模型基线 `agent-20261027T152856648100` 经 8 次修复未通过。启用改进提示后的独立运行 `agent-20261027T153902968736-ed50c33de09f426b824e1a2f823c1749` 先修复编译错误，仿真仍失败，随后 Modifier 因多次空补丁停止；续跑 `agent-20261027T154609415302-0d7e67438f184c4ca563636fc6b2c182` 仍未通过。相关测试日志和每轮 RTL 保存在各自运行目录。纯模型生成不能与参考模式的通过结果混为一谈。

运行离线回归：`.venv/bin/python -m unittest discover -s checks -v`。
