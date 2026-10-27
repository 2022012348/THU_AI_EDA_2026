# 实验记录快照

这里是从本机 `runs/` 目录备份上来的实验记录（2026-10-27）。上游仓库的 `.gitignore` 默认忽略
`runs/`，这些文件是手动 `git add -f` 纳入的；之后新产生的 run 不会被自动跟踪。

## 包含

| 目录 | 内容 |
| --- | --- |
| `agent/agent-20261027T080948039158/` | RV32I L0 的一次完整 Agent 运行：`events.json`（全部事件与流式响应）、`handoffs/`（9 个交接消息）、`artifacts/`（spec/plan/manifest）、`project/rtl/`（9 个生成文件）、`tester-01..03/`（三轮验收报告） |
| `prompt/classroom_seq1011/` | seq1011 单次 Prompt 实验（P2/P3），每个 run 含 `prompt.md`、`raw_response.txt`、`generated.sv`、`metadata.json`、`test_report.json` |

## 不包含

- `*.vcd`（功耗分析的波形，约 3.3 MB，可由 `retest` 重新生成；老师 `.gitignore` 也排除了它）
- `.venv/`、`.tools/`、`.api_key`

## 怎么复现

```sh
cd THU_AI_EDA_2026
make web      # 或 .venv/bin/python -m ai_eda retest --run-dir runs/<...>
```
