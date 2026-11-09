"""Deterministic acceptance of repair candidates, independent of model claims."""
from __future__ import annotations
from typing import Any
from ai_eda.agent.repair_focus import ticket_still_observed


def failure_state(report: dict[str, Any]) -> dict:
    failures = {(str(c.get('testcase') or c.get('test') or c.get('name') or ''), str(c.get('detail') or ''))
                for c in report.get('checks') or [] if isinstance(c, dict)}
    incomplete = {name for name, detail in failures if '等待 halted 超时' in detail
                  or 'halt timeout' in detail.lower() or 'waiting for halted' in detail.lower()}
    suites = {str(s.get('name')): ('skipped' if s.get('skipped') else 'passed' if s.get('passed') else 'failed')
              for s in report.get('test_suites') or [] if isinstance(s, dict)}
    return {'stage': report.get('stage'), 'timed_out': bool(report.get('timed_out')),
            'failed_tests': sorted({name for name, _ in failures}), 'incomplete_tests': sorted(incomplete),
            'distinct_checks': len(failures), 'suites': suites, 'passed': bool(report.get('passed'))}


def evaluate_repair(baseline: dict, candidate: dict) -> dict:
    before, after = failure_state(baseline), failure_state(candidate)
    reasons = []
    if after['passed']:
        accepted = True
        reasons.append('full acceptance passed')
    elif after['stage'] != 'simulation' or after['timed_out']:
        accepted = False
        reasons.append('candidate did not complete the acceptance simulation')
    elif before['stage'] != 'simulation' or before['timed_out']:
        accepted = True
        reasons.append('candidate restored a completed simulation')
    else:
        if ticket_still_observed(baseline,candidate):
            reasons.append('the selected retirement counterexample is still observed; repair ticket not resolved')
        regressions = sorted(set(after['incomplete_tests']) - set(before['incomplete_tests']))
        new_tests = sorted(set(after['failed_tests']) - set(before['failed_tests']))
        lost_suites = sorted(name for name, status in before['suites'].items()
                             if status != 'skipped' and after['suites'].get(name) in (None, 'skipped'))
        failed_suites = sorted(name for name, status in before['suites'].items()
                              if status == 'passed' and after['suites'].get(name) != 'passed')
        if regressions: reasons.append('new tests failed to halt: ' + ', '.join(regressions))
        if new_tests: reasons.append('previously nonfailing tests now fail: ' + ', '.join(new_tests))
        if lost_suites: reasons.append('suite coverage lost: ' + ', '.join(lost_suites))
        if failed_suites: reasons.append('previously passed suites regressed: ' + ', '.join(failed_suites))
        old_score = (len(before['incomplete_tests']), len(before['failed_tests']), before['distinct_checks'])
        new_score = (len(after['incomplete_tests']), len(after['failed_tests']), after['distinct_checks'])
        accepted = not reasons and new_score < old_score
        if not reasons:
            reasons.append('observable improvement without coverage regression' if accepted else 'no verified improvement')
    return {'accepted': accepted, 'action': 'retain' if accepted else 'rollback',
            'reasons': reasons, 'baseline': before, 'candidate': after,
            'scope': 'Conservative repair selection only. Original teacher verdicts are unchanged; retained does not mean passed.'}
