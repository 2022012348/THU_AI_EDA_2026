# Codex 交接：L1 稳定通过（2026-10-28 深夜，DeepSeek harness 交接）

> 这份文档是给 **Codex** 的续作说明。前一份 `DEEPSEEK-HARNESS-HANDOFF.md` 是 Codex 自己写的任务书（含边界与历史），本文补 **DeepSeek harness 接手后发生的所有变化**、当前真实状态、以及验证过的无效尝试。两份一起看。
> 所有数字都来自落盘记录，接手后请**重新核实**（见 §1 的命令）。

---

## 0. 一句话现状

**仍未通过 L1。** 最好成绩 **40 条失败 check**（确定性），退休 PC/指令错位那一类 bug 已修好；剩下的是 **D 通路（store 根本没写进存储器）+ 重复退休（每条指令退休两次）+ halt 超时**。
**注意：上一批"40 → 41"没有改善，纯加提示词已证明无效。**

---

## 1. 先跑这三条（核实状态，不花钱）

```sh
cd /Users/abel/THU_AI_EDA_2026
export PATH="/opt/homebrew/bin:$PATH"       # 非登录 shell 没有 iverilog/yosys

# 离线回归：应为 79 项通过
.venv/bin/python -m unittest discover -s checks -q

# 教师文件必须零改动（应为空）
git status --short -- content/tasks/homework_rv32i5

# 最近几次运行的真实结论（按 mtime 倒序）
.venv/bin/python - <<'PY'
import json, glob, os
for r in sorted(glob.glob('runs/agent/agent-*'), key=os.path.getmtime)[-5:]:
    t = sorted(glob.glob(r + '/tester-*'))
    rep = json.load(open(t[-1] + '/test_report.json')) if t else {}
    ev = json.load(open(r + '/events.json'))
    print(os.path.basename(r), '|', ev.get('status'), '|', os.path.basename(t[-1]) if t else '-',
          '| checks', len(rep.get('checks', [])), '| timeout', rep.get('timed_out'))
PY
```

---

## 2. 红线（沿用原任务书，没变）

- **不得手工改 RTL**：生成的 RTL 只能来自 Coder/Modifier 的返回。
- **不得改 `content/tasks/homework_rv32i5/`** 任何教师文件、不得放宽门槛、不得伪造退休/能力事件。
- **独立验收必须 `use_l1_reference=False`**，不得用参考 RTL 或历史通过 RTL 当种子。
- **稳定 = 同一版本工具、同一参数，3 次全新独立运行连续通过**（无 `resume_from`、无 `diagnostic_evidence`）。续跑只能用于调工具，不能算验收。
- 可以改的是：`ai_eda/` 的调度、模型调用、提示词、自动诊断、协议校验，以及 `checks/` 下的离线回归。

---

## 3. 环境与运行方式（踩过的坑都写在这里）

| 事项 | 事实 |
| --- | --- |
| Python | 仓库内 `.venv/bin/python`（3.11.5） |
| 工具链 | `/opt/homebrew/bin` 里的 `iverilog` / `vvp` / `yosys`；`~/.local/bin/sta`。**非登录 shell 默认没有这些**，必须显式加 PATH |
| 服务商 | `https://llmapi.paratera.com/v1`，模型 `DeepSeek-V4.1-Flash-1017`（`ai_eda/model/client.py`） |
| 鉴权 | `.api_key`（paratera，权限 600）。备份在 `runs/local_api_profiles/`（`deepseek_native.json` 是用户自己的官方 key）。**不要打印、不要提交** |
| 网络 | **必须直连，不要走 Clash 代理**。走代理会 `SSL_ERROR_SYSCALL`；第一次连不上时先 `unset https_proxy http_proxy all_proxy` 再试 |
| 超时 | rv32i5 四档 `timeout_seconds=120`（原来 20 s 会把仿真中途杀掉，见 §5.1） |

全新独立运行（**验收用**，会花钱）：

```sh
cd /Users/abel/THU_AI_EDA_2026
export PATH="/opt/homebrew/bin:$PATH" PYTHONPATH="$HOME/THU_AI_EDA_2026"
unset https_proxy http_proxy all_proxy HTTPS_PROXY HTTP_PROXY
export NO_PROXY="llmapi.paratera.com,127.0.0.1,localhost"
.venv/bin/python -u - <<'PY'
import json, signal, threading
from ai_eda.agent.orchestrator import run_agent
cancel = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: cancel.set())
def progress(e):
    if not e.get('streaming'):
        print(json.dumps({k: e.get(k) for k in ('run_id','node_id','status','call_index','output_tokens')}, ensure_ascii=False), flush=True)
r = run_agent(project_id='rv32i5_cache', use_l1_reference=False, thinking=False,
              max_calls=12, max_repair_attempts=4, cancel_event=cancel, on_event=progress)
print(json.dumps({'run_id': r['run_id'], 'status': r['status'], 'passed': (r.get('result') or {}).get('passed')}, ensure_ascii=False))
PY
```

调工具的续跑（**不算验收**）：

```python
r = run_agent(project_id='rv32i5_cache', use_l1_reference=False, thinking=False,
              resume_from='<确切 run 目录名>', resume_tester_attempt=<N>,
              resume_retest_checkpoint=True,
              max_calls=4, max_repair_attempts=2, ...)
```

> `resume_tester_attempt=N` 取的是 `rtl_manifest_attempt(N-1)`——语义是"tester-N 当时测的那份 RTL"。想复现第 N 轮的状态就用 N，别减一。

---

## 4. 当前真实状态（2026-10-28 22:35）

| run | 最后轮 | checks | timeout | 说明 |
| --- | --- | --- | --- | --- |
| `agent-20261028T120731264745-e823d5bd43ba4f6e9c373e38f5fa9b16` | tester-03 | **40** | 否 | 目前最好且可复现 |
| `agent-20261028T121939192439-6b4ca3cabe8745eab6970980312f18d4` | tester-02 | **40** | 否 | 同上 |
| `agent-20261028T122517643354-8ed7dcf0267f46e3b834aa7656f54c2d` | tester-03 | 41 | 否 | 加了失败摘要前置后**略差** |
| `agent-20261028T115819279860-cfe166f9b42b45ac9d56896761d03598` | tester-03 | 0 | — | 第三轮编译失败（被语法闸门拦住后没再修） |

### 剩余失败（按出现次数，来自 40 条那份报告）

| check | 次数 | 现象 |
| --- | --- | --- |
| `t08_store_fwd` | 11 | `x5 期望 0x000007ab 得到 0xa5a5a5a5` —— **store 没写进存储器**（0xa5a5a5a5 是存储器填充值） |
| `t06b_neg_imm` | 5 | `x2 期望 0x11223344 得到 0x00000000` —— load 读回 0 |
| `bench_branch_predict64` / `bench_crc32_64bytes` / `bench_array_sum64` / `bench_ooo_overlap64` | 各 3–5 | 基准程序连带失败 |
| `t06_load_store` / `t07_load_use` / `t09_branch` / `t10_jump` / `t13_dft` / `cache_line_conflict` | 各 1–2 | `等待 halted 超时`，PC 卡在 `0x29ac / 0xec / 0x80` |
| `l1_icache_old_line_preserved` | 1 | 自建探针：refill 后旧行丢失 |
| `t11_halt` | 1–3 | `x10 期望 0xab 得到 0x00`，`exit_code` 没锁存 |

### 已经修好的

- **退休 PC / 指令错位**（原来 5/5 失配）：`pc=4` 却退休 `imem[0]` 的字。模型在读到工具给的配对统计后自行改对 `if_stage`（拆分 `pc_fetch` 与 `if_pc_r`），错配归零。

---

## 5. DeepSeek harness 这轮改了什么（9 处，全部在 `ai_eda/`）

### 5.1 测量口径（最关键，先看这个）

**`agent/projects.py`**：rv32i5 四档 `timeout_seconds: 120`。
这份共享 TB 完整仿真约 **24 s**，而原来 20 s 墙钟会把 `vvp` 中途杀掉，同一份 RTL 会得到 **36 / 24 / 52** 这种飘忽的 check 数。之前几轮所谓"退化"里有一部分是**测量假象**。改完连跑两次完全一致（51 条，23.5 s / 24.0 s）。功能超时仍由 TB 内部的 500 周期等待判定，没有放水。

### 5.2 退休侧证据

**`agent/skills/retirement_observer.py`**：失配时额外输出
`imem_addr / imem_valid / imem_ready / imem_rdata / expected_at_addr / insn_at_pc_minus4 / pc_minus4 / prev_retire / prev_if`。
（`checks/test_retirement_observer.py` 的 fixture 已同步补了这几个信号。）

**`agent/subagents/common.py::_retire_pairing_summary`**：把观察结果压成一句机械统计——
`5 mismatches; retired word equals the program word at pc in 0 and at pc-4 in 5.`
模型就是靠这句定位到 pc 配对的。

**`agent/skills/retire_tail.py`（新增）**：只读探针，环形缓冲 48 条退休记录，在 `final` 块一次性打印；Tester 遇到 `等待 halted 超时` 时自动调用。
首跑抓到的关键事实：**`total_retirements=670218`，且相邻 PC 成对重复（`0x18 x2 → 0x1c x2 → …`）——每条指令退休了两次。**

### 5.3 补丁侧闸门

**`agent/subagents/modifier.py::_syntax_error`**：补丁落地前用 `iverilog -g2012 -t null` 做一次解析检查，失败就把编译器报错退回给模型当场重试，不再白占一轮 Tester。

**`agent/subagents/modifier.py::_failure_digest`**：把失败按次数排序的小表放到 prompt **最前面**（原来 20k+ Spec 在前、失败摘要在最后）。

**`agent/subagents/common.py`**：
- `MODIFIER_SYSTEM_PROMPT` 增加 iverilog 限制：`always_comb/always_ff` 里的常量段选择（如 `funct7[6:0]`）会报 `sorry: constant selects in always_* processes are not fully supported`（模型连续两轮踩同一个坑）。
- `RV32I_MODIFIER_RULES` 增加两条通用排查顺序：① 退休错配先比对 `pc / pc-4 / pc+4` 再动 stall/cache；② 取指地址必须绑定到被消费的那次响应。

**`agent/orchestrator.py::_carry_modifier_memory`**：续跑时把上游运行的 `notes / failure_fingerprint / failing_tests` 带进新运行。之前续跑 Modifier 上下文是空的，模型会重复上一轮已失败的补丁。

---

## 6. 验证过**无效**的尝试（别重复烧钱）

1. 只加文字提示/规则（三轮 40 条不变）；
2. 把失败摘要前置（40 → 41）；
3. 续跑携带 Modifier 记忆（有改善但不解决根因）；
4. 让模型自己看退休证据——只解决了 pc 配对那一类，之后它又回到 IF/icache 上打转。

**模式很明确：模型会忽略"最高频失败在 D 通路"这件事，继续改 IF 层。**

---

## 7. 下一步建议（按性价比排序）

1. **D 通路现场证据（最优先）**。两个做法，推荐后者：
   - 黑盒探针：仿 `ai_eda/agent/skills/l1_icache_probe.py`，在 `content/agent/verification/` 放一个 TB，直接例化 `dcache` / `mem_stage`，逐拍打印 `dmem_valid / dmem_we / dmem_addr / dmem_wdata / dmem_be` 与回读值；
   - **更稳**：学 `retire_tail.py` 的只读监听模式，跟着教师 TB 采样顶层 `dmem_*` 总线（不依赖内部端口名，模型改内部结构也不会失效），超时/失败时把最后 N 笔事务交给 Modifier。
2. **重复退休做成独立断言**：PC 成对出现 = 一条指令退休两次。做成探针的 pass/fail，而不是让模型自己去数 `x2`。
3. **halt 超时按 test 分组**：现在的 `retire_tail` 只给"最后一次测试"的尾部，多个测试超时时信息会被覆盖。
4. 预算纪律：每批 ≤4 次调用；先只跑 Tester（不花钱）确认证据，再决定是否让 Modifier 动手。

---

## 8. 已知的坑 / 陷阱

- **早期快照有污染**：`rtl_manifest` 里的 `implementation` 字段非 `model`/`model_repair` 的都不可信。实测 **12 个运行、153 条 `unknown`**（2026-10-27 15:46 → 10-28 02:42），那是"说不清来源"的 RTL。**干净链条从 2026-10-28 02:51 之后开始**（`agent-20261028T025122096516…` 起）。快照 sha256 与 manifest 全部吻合，说明没有事后篡改，但来源不可信就是不可信。
- 不要 `git reset` / `checkout`：**34 个文件未提交**，包含 Codex 之前的改动和本轮改动，混在一起，清掉会丢工作。
- `runs/` 已在 `.gitignore` 里；`runs/local_api_profiles/` 存着密钥备份，**别提交、别打印**。
- CLI 脚本用 `.venv/bin/python /tmp/x.py` 时 `sys.path` 是 `/tmp`，需要 `PYTHONPATH=$HOME/THU_AI_EDA_2026`。
- 端口：工作台现有 8000（旧代码）和 8003 两个实例；**别用旧端口发付费运行**，优先用 Python 路径。

---

## 9. 关键证据附录（可直接引用）

```
# 退休错位（已修好）
pc=4  insn=20000093  imem[4]=00408093  imem[0]=20000093   → 命中 pc-4，5/5

# 重复退休（未修）
total_retirements=670218  halted=1  exit=0000044e  last_test=bench_ooo_overlap64
最近 PC：0x18 x2 → 0x1c x2 → 0x20 x2 → 0x24 x2 → 0x0c x3 → …

# D 通路（未修）
t08_store_fwd: x5 期望 0x000007ab 得到 0xa5a5a5a5   （0xa5a5a5a5 = 存储器填充值，说明 store 没落地）
t06b_neg_imm : x2 期望 0x11223344 得到 0x00000000
t11_halt     : x10 期望 0x000000ab 得到 0x00000000  （exit_code 未锁存）
```

---

**建议 Codex 的第一个动作**：先跑 §1 三条命令核实，再读 §7.1 把 D 通路证据做出来；在拿到"store 事务到底有没有出现在 dmem 总线上"之前，不要再让 Modifier 改 IF。

---

## 附：交接后状态（2026-11-09 复核，DeepSeek harness）

- 代码健康：离线回归从 **79 项涨到 104 项，全过**（Codex 交接后追加了测试）；`git diff --check` 干净；`content/tasks/homework_rv32i5/` 仍 0 改动。
- **L1 仍未通过**。交接后（10-28 22:31 → 23:40）又跑了 5 批，最后一份是
  `agent-20261028T153815798813-6b7cfc6615ab454691e1781894731104/tester-01`：**71 条失败**，
  失败集中在 `t06_load_store`(21)、`cache_line_conflict`(12)、`t08_store_fwd`(10)、`t11_halt`(5)。
  证据链（`retire_tail` / `retirement_observation` / `directed_checks`）都在报告里。
- **目前最好且可复现的快照仍是 40 条**：`agent-20261028T120731264745-e823d5bd43ba4f6e9c373e38f5fa9b16`（tester-03）。
  如果要继续，建议从它续跑，而不是从 71 条那份。
- 未提交改动现为 **44 个文件**（比交接时多 10 个），依旧**不要 reset/checkout**。

### 2026-11-09 补充（零成本，未花钱跑模型）

- **发现重复劳动**：Codex 交接后已经写了 `agent/skills/data_bus_observer.py`（按 test 分组、含 cycle/we/addr/rdata）与 `signal_probe.py`，覆盖了 D 通路证据。我一度新写的 `dmem_trace.py` 与之重复，**已删除并还原 tester.py**。后续别再重复造这个轮子。
- **实测这份证据本身是有效的**：同一份 40 条快照上，D 总线 `total=134944 / stores=43 / loads=134901`；`cache_line_conflict` 与 `bench_crc32` 的 `等待周期=16` 且报 `D-memory request changed before ready`（违反 A.1 的"地址必须保持到 ready"）。
- **改了一处提示词结构**（免费）：`modifier.py::_failure_digest` 现在把每个测试的 D 总线计数**直接贴在对应失败行后面**，例如
  `- t06_load_store x21 — x2 期望 0x80ff7f01 得到 0x00000000 ［D 总线：读=8 写=4 退休load=18 退休store=3］`。
  原因是 `data_bus_observation` 在反馈里是一大段 JSON，连续多轮都没被模型用上。
- 离线回归：**104 项通过**（未跑任何付费模型调用）。

### 2026-11-09 第二轮补充（仍然零成本）

- `_failure_digest` 的 D 总线注解扩到 7 个字段，新增 **`退休总数`** 与 **`相邻重复退休`**（后者直接对应"一条指令退休两次"）。
  真实报告上现在长这样：
  ```
  - t08_store_fwd x10 — x6 期望 0xffffffff 得到 0x000007ab ［D 总线：读=8 写=4 退休load=5 退休store=2 退休总数=17 相邻重复退休=3 等待周期=0］
  - cache_line_conflict x13 — D-memory request changed before ready ［… 等待周期=16］
  - t11_halt x5 — 执行 3344 周期超过预算 72 ［… 退休总数=1023］
  ```
- 新增 `checks/test_failure_digest.py`（5 条），全量离线回归 **109 项通过**。
- 仍未发起任何付费模型调用。

### 2026-11-09 第三轮补充（零成本）

- **确定性复核**：同一份 40 条快照连跑两次 `test_rtl`，17.4 s / 17.3 s，**两次 check 集合完全一致**（39 条，差异只是探针检查不在原始 test_rtl 里）。可以确认 120 s 之后测量是可复现的。
- **新增验收脚本** `scripts/run_l1_stability.py`：连续 K 次**全新独立**运行（无 resume、`use_l1_reference=False`、无 diagnostic_evidence），输出汇总表 + JSON 记录，失败可 `--stop-on-fail`。
  **默认只打印计划，必须加 `--yes` 才花钱**：
  ```sh
  .venv/bin/python scripts/run_l1_stability.py            # 预览
  .venv/bin/python scripts/run_l1_stability.py --yes      # 跑 3 次 = 任务的"稳定通过"定义
  ```
  这就是最终验收要用的那条命令，别再用零散的手工 run_agent 声称"稳定"。
