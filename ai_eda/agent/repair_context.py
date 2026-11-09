"""Select producer/consumer source without changing the complete RTL snapshot."""
from ai_eda.agent.skills.l1_id_hazard_probe import _module_ports


def select_repair_context(files: dict, plan: dict, ticket: dict | None, extra_paths=()) -> dict:
    presence=(ticket or {}).get('pipeline_token_presence') or {}
    stages=presence.get('stages') or []
    hits=[i for i,s in enumerate(stages) if s.get('valid_samples',0)>0]
    if not hits or hits[-1]>=len(stages)-1:return dict(files)
    index=hits[-1];producer=stages[index]['stage'];consumer=stages[index+1]['stage']
    def owner(stage):
        port='retire_pc' if stage=='retire' else stage+'_pc'
        candidates=[]
        for m in plan.get('modules') or []:
            if m.get('name')==plan.get('top_module') or m.get('file') not in files:continue
            try:ports=_module_ports(files[m['file']],m['name'])
            except ValueError:continue
            if ports.get(port)==('output',32):candidates.append(m['file'])
        return candidates[0] if len(candidates)==1 else None
    a,b=owner(producer),owner(consumer)
    if not a or not b:return dict(files)
    chosen={a,b,*extra_paths}
    chosen.update(m['file'] for m in plan.get('modules',[]) if m.get('name')==plan.get('top_module'))
    return {p:text for p,text in files.items() if p in chosen}


def requested_context(files: dict, provided: dict, request) -> dict:
    if (not isinstance(request,list) or not 1<=len(request)<=3
            or any(not isinstance(p,str) or p not in files for p in request)):
        raise ValueError('request_context必须是1~3个实际计划RTL路径；不能读取项目外文件')
    result={p:files[p] for p in request if p not in provided}
    if not result:raise ValueError('这些源码已经提供，请不要重复申请')
    return result
