"""Bounded ablation of model-authored file changes; never invent RTL edits."""
from pathlib import Path
from ai_eda.agent.subagents.common import safe_project_path


def restore_checkpoint(runtime, handoff: Path) -> None:
    artifacts=runtime.read_handoff(handoff)['payload']['artifacts']
    manifest=runtime.read_json_artifact(artifacts['rtl_manifest'])
    for entry in manifest['files']:
        target=safe_project_path(runtime.run_dir,entry['path'])
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(runtime.read_text_artifact(entry['artifact']),encoding='utf-8')


def build_file_ablations(runtime, baseline: Path, candidate_input: Path, attempt: int, limit: int=2) -> list[Path]:
    """Test individual model-changed files only when interfaces are unchanged.

    The entire rejected candidate remains preserved. Subsets use exact bytes
    from its manifest and from the retained baseline, with original provenance.
    """
    base=runtime.read_handoff(baseline)['payload']['artifacts']
    candidate=runtime.read_handoff(candidate_input)['payload']
    artifacts=candidate['artifacts']
    if candidate.get('candidate_ablation') or limit<=0:
        return []
    # Interface repairs may require multiple files atomically; never split them.
    if runtime.read_json_artifact(base['plan']) != runtime.read_json_artifact(artifacts['plan']):
        return []
    old={e['path']:e for e in runtime.read_json_artifact(base['rtl_manifest'])['files']}
    new={e['path']:e for e in runtime.read_json_artifact(artifacts['rtl_manifest'])['files']}
    if old.keys()!=new.keys() or any(e.get('implementation') not in {'model','model_repair'} for e in [*old.values(),*new.values()]):
        return []
    old_text={path:runtime.read_text_artifact(e['artifact']) for path,e in old.items()}
    new_text={path:runtime.read_text_artifact(e['artifact']) for path,e in new.items()}
    changed=sorted(path for path in old if old_text[path]!=new_text[path])
    if not 2<=len(changed)<=3:
        return []
    result=[]
    for index,path in enumerate(changed[:min(2,limit)],1):
        files=dict(old_text); files[path]=new_text[path]
        manifest=runtime.snapshot_rtl_manifest(files,f'ablation_{attempt}_{index}')
        for entry in manifest['files']:
            provenance=new[entry['path']] if entry['path']==path else old[entry['path']]
            for key in ('implementation','original_implementation'):
                if key in provenance: entry[key]=provenance[key]
        ref=runtime.write_json_artifact(f'rtl_manifest_ablation{attempt}_{index}.json',manifest)
        result.append(runtime.write_handoff('repair_controller','tester',{
            'candidate_ablation':True,'ablation_of':attempt,'changed_paths':[path],
            'artifacts':{'spec':base['spec'],'plan':base['plan'],'rtl_manifest':ref}},
            attempt=attempt*10+index,label=f'Bounded model-patch ablation: {path}'))
    return result
