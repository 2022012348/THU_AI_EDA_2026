"""A single evidence-backed repair ticket, with an AI view separate from verdicts."""
from __future__ import annotations
import hashlib
import json


def make_repair_ticket(report: dict) -> dict | None:
    observation=report.get('retirement_observation') or {}
    if observation.get('observations'):
        row=observation['observations'][0]
        kind='retirement_pairing'
        rule='Retired instruction word must match the instruction at its retired PC.'
    elif observation.get('sequence_observations'):
        row=observation['sequence_observations'][0]
        kind='retirement_fallthrough'
        rule='After the observed non-control RV32I predecessor, the next retired PC must equal previous_pc+4. Explain this counterexample before unrelated halt/cache symptoms.'
    else:
        probes={str(c.get('name')) for c in report.get('directed_checks') or [] if isinstance(c,dict)}
        checks=report.get('teacher_checks',report.get('checks') or [])
        row=next((c for c in checks if isinstance(c,dict) and str(c.get('name')) not in probes
                  and not str(c.get('name','')).startswith('l1_')),None)
        if row is None:return None
        kind='teacher_assertion';rule='Explain and remove this concrete teacher failure while preserving other behavior.'
    test=str(row.get('test') or row.get('testcase') or row.get('name') or '').strip()
    identity={'kind':kind,'testcase':test,'evidence':row}
    ticket_id=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    ticket={'id':ticket_id,**identity,'required_property':rule,
            'scope':'Automatic evidence selection, not a root-cause verdict. Original full teacher report remains authoritative.'}
    expected=row.get('expected_pc') if kind=='retirement_fallthrough' else row.get('pc')
    presence=observation.get('pipeline_token_presence') or {}
    if (presence.get('target_pc')==expected and any(r.get('test')==test
            for r in observation.get('pipeline_history') or [])):
        ticket['pipeline_token_presence']=observation['pipeline_token_presence']
        hits=[s for s in presence.get('stages',[]) if s.get('valid_samples',0)>0]
        if hits:
            last=hits[-1]
            try: cycle=int(last['last_cycle'])
            except (TypeError,ValueError,KeyError): cycle=None
            if cycle is not None:
                ticket['boundary_window']={'last_observed_stage':last['stage'],'rows':[
                    r for r in observation.get('pipeline_history',[]) if r.get('test')==test
                    and str(r.get('cycle','')).isdigit() and abs(int(r['cycle'])-cycle)<=2],
                    'scope':'Local window around the last observed target PC-tag. This is not a unique token identity or a root-cause verdict.'}
    return ticket


def focused_report(report: dict) -> dict:
    ticket=report.get('repair_ticket') or make_repair_ticket(report)
    if not ticket:return report
    test=ticket['testcase'];view=dict(report,repair_ticket=ticket)
    view['checks']=[c for c in report.get('teacher_checks',report.get('checks') or []) if isinstance(c,dict)
                    and str(c.get('test') or c.get('testcase') or c.get('name') or '').strip()==test]
    view['trace']=[row for row in report.get('trace') or [] if isinstance(row,dict)
                   and str(row.get('test') or row.get('testcase') or '').strip()==test]
    view['directed_checks']=[]
    view['test_suites']=[]
    view['performance']={}
    view.pop('retire_tail',None)
    if ticket['kind'].startswith('retirement_'):
        view.pop('structural_diagnostics',None)
    if isinstance(report.get('data_bus_observation'),dict):
        view['data_bus_observation']={**report['data_bus_observation'],'tests':[
            row for row in report['data_bus_observation'].get('tests',[]) if row.get('test')==test]}
    if isinstance(report.get('retirement_observation'),dict):
        view['retirement_observation']=dict(report['retirement_observation'])
        for key in ('observations','sequence_observations'):
            view['retirement_observation'][key]=[row for row in report['retirement_observation'].get(key,[]) if row.get('test')==test]
        view['retirement_observation']['pipeline_history']=[row for row in report['retirement_observation'].get('pipeline_history',[]) if row.get('test')==test]
    return view


def ticket_still_observed(baseline: dict, candidate: dict) -> bool:
    ticket=baseline.get('repair_ticket') or make_repair_ticket(baseline)
    if not ticket or not ticket['kind'].startswith('retirement_'):return False
    obs=candidate.get('retirement_observation') or {};old=ticket['evidence']
    keys=('test','previous_pc','previous_insn') if ticket['kind']=='retirement_fallthrough' else ('test','pc')
    rows=obs.get('sequence_observations' if ticket['kind']=='retirement_fallthrough' else 'observations') or []
    return any(all(str(row.get(k,'')).strip()==str(old.get(k,'')).strip() for k in keys) for row in rows)
