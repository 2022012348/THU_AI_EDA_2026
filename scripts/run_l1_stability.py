#!/usr/bin/env python3
"""L1 独立验收跑批：连续 K 次全新运行（无 resume、无参考实现）。

任务的"稳定通过"定义是：同一版本工具、同一参数，连续 K 次**独立**运行全部通过。
这个脚本只负责把这件事跑成一份可引用的记录，不做任何重试、不注入诊断、不改 RTL。

用法（会花钱，默认只打印计划，必须显式 --yes 才真的跑）：

    .venv/bin/python scripts/run_l1_stability.py                 # 只看计划
    .venv/bin/python scripts/run_l1_stability.py --yes           # 跑 3 次
    .venv/bin/python scripts/run_l1_stability.py --yes --runs 2 --max-calls 8

每次运行之间的唯一差别是 run_id；参数、项目、工具版本都不变。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="连续 K 次独立运行的 L1 验收")
    parser.add_argument("--runs", type=int, default=3, help="独立运行次数（默认 3）")
    parser.add_argument("--project", default="rv32i5_cache", help="项目 id")
    parser.add_argument("--max-calls", type=int, default=12, help="单次运行模型调用上限")
    parser.add_argument("--max-repair-attempts", type=int, default=4, help="单次运行修复轮次上限")
    parser.add_argument("--thinking", action="store_true", help="开启思考模式（默认关闭）")
    parser.add_argument("--out", default=None, help="结果 JSON 路径")
    parser.add_argument("--stop-on-fail", action="store_true", help="任一次失败即停止")
    parser.add_argument("--yes", action="store_true", help="确认会产生模型费用")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.runs < 1:
        print("--runs 必须 >= 1", file=sys.stderr)
        return 2

    plan = {
        "project": args.project,
        "runs": args.runs,
        "max_calls": args.max_calls,
        "max_repair_attempts": args.max_repair_attempts,
        "thinking": args.thinking,
        "use_l1_reference": False,
        "resume_from": None,
        "diagnostic_evidence": None,
    }
    print("计划：", json.dumps(plan, ensure_ascii=False))
    if not args.yes:
        print("\n这是计划预览。真正运行会消耗模型额度，加 --yes 才会执行。")
        return 0

    from ai_eda.agent.orchestrator import run_agent

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, object]] = []
    overall_ok = True

    for index in range(1, args.runs + 1):
        print(f"\n=== 独立运行 {index}/{args.runs} ===", flush=True)
        clock = time.time()
        try:
            result = run_agent(
                project_id=args.project,
                use_l1_reference=False,
                thinking=args.thinking,
                max_calls=args.max_calls,
                max_repair_attempts=args.max_repair_attempts,
            )
            report = result.get("result") or {}
            row = {
                "run": index,
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "passed": bool(report.get("passed")),
                "stage": report.get("stage"),
                "tester_attempts": report.get("tester_attempts"),
                "duration_s": round(time.time() - clock, 1),
                "error": result.get("error"),
            }
        except Exception as error:  # 记录失败原因，不吞掉
            row = {
                "run": index,
                "run_id": None,
                "status": "error",
                "passed": False,
                "stage": None,
                "tester_attempts": None,
                "duration_s": round(time.time() - clock, 1),
                "error": f"{type(error).__name__}: {error}",
            }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not row["passed"]:
            overall_ok = False
            if args.stop_on_fail:
                print("首次失败即停止（--stop-on-fail）。", flush=True)
                break

    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plan": plan,
        "runs": rows,
        "all_passed": overall_ok and len(rows) == args.runs,
        "completed_runs": len(rows),
    }
    out_path = Path(args.out) if args.out else (
        PROJECT_ROOT / "runs" / f"l1-stability-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== 汇总 ===")
    print(f"{'#':>2}  {'passed':<6} {'stage':<10} {'attempts':<8} {'秒':>6}  run_id")
    for row in rows:
        print(f"{row['run']:>2}  {str(row['passed']):<6} {str(row['stage']):<10} "
              f"{str(row['tester_attempts']):<8} {row['duration_s']:>6}  {row['run_id']}")
    print(f"\n全部通过：{summary['all_passed']}（{len(rows)}/{args.runs} 次完成）")
    print(f"记录：{out_path}")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
