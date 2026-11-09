# 当前交接：EDA Agent 自主稳定通过 L1

日期：2026-10-28（北京时间）。目标未完成，独立通过次数 **0**。这是当前入口；旧记录见 `runs/analysis/handoff-history-20261028.md`、`CODEX-RESUME-2026-10-28.md`。

## 当前状态

**已按用户要求在Codex五小时额度85%已用时暂停。** 没有新的付费运行需要等待。用户可将本文交给DeepSeek harness继续；Codex在用户恢复前不再启动实验。接手仍须核实进程。

**最近已结束批** `agent-20261028T153815798813-6b7cfc6615ab454691e1781894731104`：日志 `/tmp/eda-codex-frontier-resume.log`。只发生1次模型调用，16k思考输出触顶，未形成完整补丁，部分输出未采纳。`result.json.selected_report=tester-01/test_report.json`，保留71条失败；未通过。这是诊断续跑，不能计为独立验收。

上一批 `agent-20261028T151640413142-64ec58d5d61b4e44a7683f2b32c650d2`：2次调用；取得波形后的Modifier思考触及16k输出上限，完整补丁未形成，部分输出未采纳，正常保留71条失败的tester-01并停止。不得盲目重复同设置的截断调用。

最新离线 **104项通过**，`git diff --check`通过。老师目录Git状态空，生成RTL没有手工编辑。

## 边界与验收

- 仓库 `/Users/abel/THU_AI_EDA_2026`，不是聊天cwd另一个repo。
- 不修改 `content/tasks/homework_rv32i5/` 任何老师文件，不放宽断言、伪造退休/能力事件、按测试程序硬编码。
- 不手工改生成RTL；只允许Coder/Modifier模型产物或其精确补丁。自动回退/隔离候选只复制已有模型输出字节，并保留所有来源和原报告。
- 不使用参考或历史通过RTL种子，不向独立验收注入人工针对某快照写的诊断。
- 允许改框架、模型调用、prompt、自动验证与诊断、离线回归。
- 稳定至少同版本同参数 **3次全新独立运行连续通过**：`use_l1_reference=False`，无resume、无diagnostic_evidence。诊断续跑即使通过也不计。
- 学生预算：单批调用限额、一次一个付费运行。先本地取证再调用，禁止机械重复无效调用或扩大思考上限来追截断。

## 当前 Tester ↔ Modifier 协议

1. 原始teacher_checks和完整报告保留。`repair_focus.py`自动选一张修复单：先PC/word错配，再普通RV32I指令的pc+4退休顺序反例，否则原教师首个失败。模型只看本case详细证据，必须返回准确ticket_id。
2. 同一具体退休反例仍观察到时，即使无关错误减少也拒绝该补丁。控制器还拒绝新增halt超时、新失败测试、suite覆盖退化。全Teacher通过才是通过。
3. `repair_control.py` / orchestrator保存较好checkpoint，退化/无改善回退。2次连续模型候选无改善停止当前批；JSON/语法失败、预算耗尽、思考截断均保留已测基线并写result.json。
4. `result.json.selected_report`指向真正保留的Tester。默认resume恢复它，而非最后被拒绝候选。不能只看最后tester目录或错误条数。
5. `repair_candidates.py`：不改接口计划的2~3文件模型补丁被拒绝后，最多做2个文件隔离候选，原教师完整复测，来源必须model/model_repair；不拆接口耦合补丁。隔离测试不调用模型，不占模型修复轮数，总验收次数<=1+3*max_repair_attempts。
6. `request_observation`让Modifier先问Tester：最多10个受限真实DUT路径，独立只读重放，最多48拍。最多一次成功请求；首请求失败可纠正一次；每轮最多3次模型交互、2次校验失败。request/answer/hash/log分开保存，重试不覆盖。
7. `signal_probe.py`一个不存在的data信号不会丢弃所有有效信号：只去掉编译器明确确认缺失者，至多重编译一次，不改名、不换trigger，返回observed_partial及signal_map。坏trigger/全坏仍error。
8. 模型预算现在放在**证据之后**：Reviewer仅非思考观测规划、max3000；Modifier无有效波形时非思考，得到有效波形后low thinking/max16000。截断不采纳部分补丁，不扩大预算重试。自动流水历史已覆盖本ticket时直接使用，省去重复Reviewer/probe调用。
9. JSON/锚点/语法重试保留同一个功能假设，仅修表达/编译错误；no-op才要求换方案。编译反馈优先真正error，非致命constant-select敏感列表警告不能当编译失败。
10. Planner有生成前协议审查，非思考max6000；输出timing_contract<=4000字符和最多3个内部接口更新，保留plan_draft/review。Plan内部notes是模型提案，允许被实际反例推翻；Spec与顶层外部合同不可改。

## 最新核心证据与自动流水历史

`retirement_observer.py`独立只读观察，不改老师TB/DUT，不用于伪造通过：
- 普通load/store/ALU/LUI/AUIPC前驱后，下次退休PC必须pc+4（无中断约定）；branch/JAL/JALR/system排除，reset/test切换清历史。
- 同时从老师当前imem读取expected_next_insn并标opcode类型。当前反例：pc4 ADDI 00408093 后仍退休pc4，gap11~12拍；应为pc8、0010a023、**store**。不要再猜成pc8 JAL。
- `pipeline_history.py`只识别顶层实际声明且位宽匹配的 if_id/id_ex/ex_mem/mem_wb PC/valid，至少2级才启用；其它拓扑不猜。保存反例前最多32拍，只读，不新增验收门槛。
- 免费实测 `runs/analysis/pipeline-history-71-check/result.json`：目标PC8在IF/ID有效样本2次、ID/EX2次、EX/MEM2次，MEM/WB和retire均0次。窗口只25拍，最后EX/MEM为cycle24。**这是窗口内tag存在性，不是已证明故障模块；循环不同迭代可能同PC。**
- 修复单附pipeline_token_presence及最后出现处附近±2拍boundary_window，放在模型prompt开头；不要让模型无依据从整颗CPU重猜。原始完整history/report仍留存。

## 环境、密钥和验证

- `.venv/bin/python`；`PATH=/opt/homebrew/bin:$PATH`；临时脚本需PYTHONPATH指向仓库。
- API保持 `https://llmapi.paratera.com/v1` / `DeepSeek-V4.1-Flash-1017`。`.api_key`被忽略，勿输出、提交或复制到MD。忽略的runs/local_api_profiles也含密钥备份。
- 直连，清空http(s)/all_proxy大小写；NO_PROXY包含服务域名和localhost。
- 不用旧网页服务发付费任务；有旧8000/8003服务可能加载旧代码。
- 不git reset/checkout清工作树，不清runs；所有历史修改未提交。

```sh
cd /Users/abel/THU_AI_EDA_2026
PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m unittest discover -s checks -q
git diff --check
git status --short -- content/tasks/homework_rv32i5
ps -axo pid,etime,command | rg '[e]da-codex-|[r]un_agent'
tail -n 8 /tmp/eda-codex-frontier-resume.log
```

## 尚未付费验证的新源码上下文功能

新增 `repair_context.py`：根据窗口内最后出现的PC-tag，实际解析模块output PC端口，选择生产者、下级消费者及顶层的源码。无法明确匹配时回退完整源码视图。编译/验收始终使用全部RTL。模型可返回带ticket_id的 `request_context:[计划RTL路径]`，每轮一次最多3个文件；只读当前快照，返回内容与SHA，不能读取 .api_key 等项目外文件，不能修改未读源码。交互耗尽但没有补丁时安全保留基线。

已验证：本样本10文件中提供 rv32i5/ex_stage/mem_stage 三文件，RTL字符量61543→32267，约减少48%（不包括Spec/Plan，也不是计费token统计）。离线测试覆盖申请遗漏源码再补丁、完整manifest不丢文件、非法路径拒绝。**尚未运行这个源码筛选版本的付费实验**，接手应先按下面小预算命令验证，不要声称L1已过。

## 下一步执行（先确认没有其他付费进程）

先读当前结果/裁决/波形，不要直接循环下列命令。如果当前批已有完整result.json，可取真正保留的checkpoint做至多4次调用的小批验证。以下诊断不计独立验收：

```sh
cd /Users/abel/THU_AI_EDA_2026
export PATH="/opt/homebrew/bin:$PATH"
unset https_proxy http_proxy all_proxy HTTPS_PROXY HTTP_PROXY ALL_PROXY
export NO_PROXY="llmapi.paratera.com,127.0.0.1,localhost"
.venv/bin/python -u - <<'PY'
import json,signal,threading
from pathlib import Path
from ai_eda.agent.orchestrator import run_agent
src='agent-20261028T153815798813-6b7cfc6615ab454691e1781894731104'
p=Path('runs/agent')/src/'result.json'
if not p.exists(): raise RuntimeError('当前批未完整结束；先核实进程/报告，勿重复启动。')
result=json.loads(p.read_text())
if result.get('passed'): raise RuntimeError('该诊断已过：冻结版本并做全新独立验收，不再修复。')
ref=result['selected_report']; attempt=int(Path(ref).parent.name.split('-')[-1])
cancel=threading.Event()
for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:cancel.set())
def log(e):
 if not e.get('streaming'):print(json.dumps({k:e.get(k) for k in ('run_id','node_id','status','call_index','output_tokens')},ensure_ascii=False),flush=True)
r=run_agent(project_id='rv32i5_cache',use_l1_reference=False,thinking=False,
 resume_from=src,resume_tester_attempt=attempt,resume_retest_checkpoint=True,
 max_calls=4,max_repair_attempts=2,max_tokens=16000,cancel_event=cancel,on_event=log)
print(r['run_id'],r['status'],flush=True)
PY
```

如果源码筛选版本仍因16k思考截断或同反例无改善，先检查模型有没有申请缺失的cache/hazard/WB源码、上下文筛选是否实际生效，以及边界窗口是否足以支持假设。不要直接扩大输出预算或机械重复。必要时改进自动控制依赖源码补充或把编译/行为反馈进一步分层。不得手工塞特定RTL答案；原始全部RTL与Spec仍是编译/验收输入，不能删需求或模块。

获得诊断通过后，冻结代码和参数，用无resume的新运行做3次连续独立验收；原 `/tmp/eda-codex-independent.py`会在每次运行记录framework_signature.json（框架和老师文件哈希），可参考其写法。一次失败就重新审视工具，不把不同版本/旧参考通过混算。
