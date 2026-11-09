"""经过教师 TB 验证的 L1 RV32I 参考实现（Coder fallback）。"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ai_eda.config import AGENT_CONTENT_ROOT

REFERENCE_ROOT = AGENT_CONTENT_ROOT / "skills" / "rv32i5_l1_reference"


def load_reference(project_id: str) -> dict[str, str]:
    if project_id != "rv32i5_cache" or not REFERENCE_ROOT.is_dir():
        return {}
    return {
        f"rtl/{path.name}": path.read_text(encoding="utf-8")
        for path in sorted(REFERENCE_ROOT.glob("*.sv"))
    }


# Reference files form a single dependency-closed design.  Copying a subset
# while generating the remaining modules from a different plan is unsafe.
REFERENCE_MODULES = (
    "rv32i5", "if_stage", "id_stage", "ex_stage", "mem_stage",
    "wb_stage", "hazard_unit", "forwarding_unit", "alu", "icache", "dcache",
)


def build_reference_plan(reference: dict[str, str]) -> dict[str, Any]:
    """Derive the effective interface contract directly from the bundled RTL.

    This deliberately accepts only the known, plain ANSI module declarations of
    this bundle.  It fails closed if the bundle changes to a format we cannot
    represent accurately, instead of inventing a contract for the Modifier.
    """
    modules: list[dict[str, str]] = []
    for name in REFERENCE_MODULES:
        path = f"rtl/{name}.sv"
        source = reference.get(path)
        if not isinstance(source, str):
            raise ValueError(f"L1 参考工程缺少必需文件：{path}")
        match = re.match(
            r"\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*;",
            source, re.DOTALL,
        )
        if not match or match.group(1) != name:
            raise ValueError(f"L1 参考模块声明无法解析或与文件名不符：{path}")
        ports = match.group(2).strip()
        if not ports or not all(re.match(r"\s*(?:input|output|inout)\b", item)
                                for item in ports.split(",")):
            raise ValueError(f"L1 参考模块端口无法可靠解析：{path}")
        modules.append({
            "name": name, "file": path,
            "description": "L1 reference implementation",
            "interfaces": ports,
        })
    return {
        "project_name": "rv32i5_l1_reference",
        "top_module": "rv32i5",
        "modules": modules,
        "notes": ("The effective plan is derived from the complete bundled L1 reference RTL. "
                  "Use the actual ports listed above; the model's planner proposal is not its interface contract."),
        "implementation_source": "reference",
    }
