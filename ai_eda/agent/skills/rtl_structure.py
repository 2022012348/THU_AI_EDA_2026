"""Read-only Yosys structural evidence for autonomous repair, not a TB oracle."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def inspect_rtl_structure(source: Path, top: str, output_dir: Path, timeout: int = 15) -> dict:
    executable = shutil.which('yosys')
    if not executable:
        return {'status': 'unavailable', 'issues': [], 'detail': 'yosys not installed'}
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top):
        return {'status': 'error', 'issues': [], 'detail': 'invalid top module'}
    output_dir.mkdir(parents=True, exist_ok=True)
    # Copy the exact tested snapshot; never rewrite the design or teacher TB.
    (output_dir / 'rtl.sv').write_bytes(source.read_bytes())
    script = output_dir / 'inspect.ys'
    script.write_text(f'read_verilog -sv rtl.sv\nhierarchy -check -top {top}\nproc\nflatten\nopt_clean\ncheck\n', encoding='utf-8')
    try:
        result = subprocess.run([executable, '-Q', '-T', '-s', 'inspect.ys'], cwd=output_dir,
                                capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'issues': [], 'detail': 'structural check timed out; no conclusion'}
    log = result.stdout + '\n' + result.stderr
    (output_dir / 'yosys.log').write_text(log, encoding='utf-8')
    issues = []
    seen = set()
    for line in log.splitlines():
        if not re.search(r'Warning:|ERROR:', line):
            continue
        # Array lowering is routine information, not a correctness diagnosis.
        if 'Replacing memory' in line:
            continue
        key = re.sub(r'\[\d+\]', '[bit]', line.strip())
        if key not in seen:
            issues.append(line.strip()[:700])
            seen.add(key)
    return {'status': 'completed' if result.returncode == 0 else 'error',
            'return_code': result.returncode, 'issues': issues[:24],
            'omitted_issue_groups': max(0, len(issues) - 24),
            'scope': 'Static Yosys hierarchy/proc/check output. Warnings are evidence to investigate, not proof of the behavioral root cause.'}
