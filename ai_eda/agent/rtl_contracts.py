"""Conservative extraction of RTL module header contracts for repair handoffs.

This parser intentionally accepts a subset of ANSI SystemVerilog. If a header
uses an unfamiliar construct it raises rather than inventing an interface.
It is not a substitute for compilation or verification.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_IDENT = r"[A-Za-z_][A-Za-z0-9_$]*"
_MODULE = re.compile(r"\bmodule\s+(?:automatic\s+)?(" + _IDENT + r")\b")
_COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_PORT = re.compile(r"(" + _IDENT + r")\s*(?:\[[^\[\]]+\]\s*)*(?:=.*)?$")


def _group(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "(":
        raise ValueError("RTL 模块头缺少括号")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == '"':
            raise ValueError("RTL 模块头含字符串，无法安全提取接口")
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    raise ValueError("RTL 模块头括号未闭合")


def _split_ports(text: str) -> list[str]:
    if not text.strip():
        return []
    # Commas inside packed dimensions, function expressions, or array ranges
    # are not port separators.
    parts: list[str] = []
    opening = {"(": ")", "[": "]", "{": "}"}
    closing = {value: key for key, value in opening.items()}
    stack: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in opening:
            stack.append(char)
        elif char in closing:
            if not stack or stack.pop() != closing[char]:
                raise ValueError("RTL 端口括号不匹配")
        elif char == "," and not stack:
            parts.append(text[start:index].strip())
            start = index + 1
    if stack:
        raise ValueError("RTL 端口括号不匹配")
    parts.append(text[start:].strip())
    return parts


def extract_module_header(source: str, expected_name: str, *, allow_duplicate_ports: bool = False) -> dict[str, Any]:
    if not isinstance(source, str):
        raise ValueError("RTL 内容无效")
    # Quoted strings in RTL bodies are legal, but source declarations must not
    # use a misleading module token inside one. Strip quoted literals first.
    sanitized = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
    sanitized = _COMMENT.sub(" ", sanitized)
    matches = list(_MODULE.finditer(sanitized))
    if len(matches) != 1 or matches[0].group(1) != expected_name:
        raise ValueError(f"RTL 模块声明缺失、重复或名称与计划不符：{expected_name}")
    match = matches[0]
    cursor = match.end()
    while cursor < len(sanitized) and sanitized[cursor].isspace():
        cursor += 1
    parameters = ""
    if cursor < len(sanitized) and sanitized[cursor] == "#":
        cursor += 1
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        parameters, cursor = _group(sanitized, cursor)
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
    ports = ""
    if cursor < len(sanitized) and sanitized[cursor] == "(":
        ports, cursor = _group(sanitized, cursor)
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
    if cursor >= len(sanitized) or sanitized[cursor] != ";":
        raise ValueError(f"RTL 模块头无法解析：{expected_name}")
    port_names: set[str] = set()
    direction = None
    for item in _split_ports(ports):
        if not item or '"' in item or "\\" in item:
            raise ValueError(f"RTL 端口无法解析：{expected_name}")
        found = re.match(r"^(input|output|inout)\b", item)
        if found:
            direction = found.group(1)
        elif direction is None:
            raise ValueError(f"RTL 使用非 ANSI 端口，无法安全提取：{expected_name}")
        name_match = _PORT.search(item)
        if (not name_match or (name_match.group(1) in port_names and not allow_duplicate_ports)
                or name_match.group(1) in {"input", "output", "inout", "wire", "logic", "reg", "signed", "unsigned"}):
            raise ValueError(f"RTL 端口名称缺失或重复：{expected_name}")
        port_names.add(name_match.group(1))
    return {
        "name": expected_name,
        "parameters": re.sub(r"\s+", " ", parameters).strip(),
        "interfaces": ports.strip(),
        # Token-based comparison ignores spacing but not identifiers or syntax.
        "signature": re.sub(r"\s+", "", ports),
    }


def reconcile_plan_interfaces(
    plan: dict[str, Any], files: dict[str, str], changed: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """Derive a new plan from changed RTL; reject top/parameter alterations."""
    modules = plan.get("modules")
    if not isinstance(modules, list):
        raise ValueError("计划缺少 modules")
    updated = copy.deepcopy(plan)
    changed_interfaces: list[str] = []
    for module in updated["modules"]:
        if not isinstance(module, dict):
            raise ValueError("计划模块格式无效")
        path, name = module.get("file"), module.get("name")
        if path not in changed:
            continue
        if not isinstance(path, str) or not isinstance(name, str) or path not in files:
            raise ValueError("RTL 变更无法映射到计划模块")
        # A previous compile may have failed precisely because an internal
        # module declares a port twice. Permit inspecting that old signature;
        # the replacement must still pass strict parsing below.
        old = extract_module_header(files[path], name, allow_duplicate_ports=name != plan.get("top_module"))
        new = extract_module_header(changed[path], name)
        if old["parameters"] != new["parameters"]:
            raise ValueError(f"修复不能改变模块参数：{name}")
        if old["signature"] != new["signature"]:
            if name == plan.get("top_module"):
                raise ValueError("修复不能改变顶层对外接口")
            module["interfaces"] = new["interfaces"]
            changed_interfaces.append(path)
    return updated, changed_interfaces
