"""Shared human-readable reporting for test reports.

Both the sub-agent feedback layer and the persisted run payload use these
helpers so a report renders identically in the UI, history, and Modifier
feedback.
"""

from __future__ import annotations

from typing import Any

_STAGE_LABELS = {"compile": "Compile", "simulation": "Simulation"}


def stage_label(stage: str | None) -> str:
    return _STAGE_LABELS.get(stage or "", stage or "Unknown stage")


def report_summary(report: dict[str, Any] | None) -> str:
    if report is None:
        return "Verification has not run yet."
    if report.get("passed"):
        summary = f"Teacher TB passed ({stage_label(report.get('stage'))})."
        capability = report.get("cpu_capability") or {}
        level = capability.get("verified_level", capability.get("level"))
        if level is not None:
            summary += f" Verified CPU level: L{level}."
        return summary
    checks = report.get("checks") or []
    if report.get("teacher_passed") is True:
        details = ", ".join(item.get("name", "check") for item in checks[:4])
        suffix = f"; directed checks: {details}" if details else ""
        return f"Teacher TB passed, but additional verification did not pass{suffix}."
    failed = ", ".join(item.get("name", "check") for item in checks[:4])
    suffix = f"; failed checks: {failed}" if failed else ""
    return f"Teacher TB failed ({stage_label(report.get('stage'))}){suffix}."
