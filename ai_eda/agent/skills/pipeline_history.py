"""Read-only ring trace for explicitly recognized top-level pipeline PC/valid nets."""
from __future__ import annotations
import re

T='tb_agent_rv32i5.u_teacher_tb.'


def add_pipeline_history(observer: str, rtl: str) -> tuple[str,list[str]]:
    clean=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',' ',rtl)
    top=re.search(r'\bmodule\s+rv32i5\b[\s\S]*?\bendmodule\b',clean)
    if not top:return observer,[]
    declared={}
    for raw in re.findall(r'\b(?:wire|logic|reg)\b([^;]*);',top.group()):
        m=re.match(r'\s*(?:(?:signed|unsigned)\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*([\s\S]*)',raw)
        if not m:continue
        width=abs(int(m[1])-int(m[2]))+1 if m[1] is not None else 1
        for item in m[3].split(','):
            name=re.match(r'\s*([A-Za-z_][A-Za-z0-9_$]*)\s*(?:=|$)',item)
            if name:declared[name[1]]=width
    stages=[p for p in ('if_id','id_ex','ex_mem','mem_wb')
            if declared.get(p+'_pc')==32 and declared.get(p+'_valid')==1]
    if len(stages)<2:return observer,[]
    fields=[]
    for prefix in stages:
        fields += [(prefix+'_pc',32,T+'dut.'+prefix+'_pc'),
                   (prefix+'_valid',1,T+'dut.'+prefix+'_valid')]
    fields += [('retire_pc',32,T+'dbg_retire_pc'),('retire_valid',1,T+'dbg_retire_valid')]
    fields += [(n,1,T+'dut.'+n) for n in ('if_stall','id_stall','ex_flush','mem_stall','wb_stall','ex_redirect_valid') if declared.get(n)==1]
    declarations=['integer ah_head=0,ah_count=0,ah_i,ah_j; reg ah_printed=0; integer ah_cycle[0:31];']
    for i,(_,width,_) in enumerate(fields):declarations.append(f'reg [{width-1}:0] ah_{i}[0:31];')
    sample=['if ('+T+'rst_n) begin','ah_cycle[ah_head]=sequence_cycle;']
    sample += [f'ah_{i}[ah_head]={path};' for i,(_,_,path) in enumerate(fields)]
    sample += ['ah_head=(ah_head+1)%32; if(ah_count<32) ah_count=ah_count+1; end']
    fmt='|'.join(name+'=%h' for name,_,_ in fields)
    args=', '.join(f'ah_{i}[ah_j]' for i in range(len(fields)))
    dump=f'''if(!ah_printed) begin
      ah_printed=1;
      for(ah_i=0;ah_i<ah_count;ah_i=ah_i+1) begin
        ah_j=(ah_head+32-ah_count+ah_i)%32;
        $display("AI_EDA_RETIRE_OBSERVATION|kind=stage_history|test=%s|cycle=%0d|{fmt}", {T}cur_test, ah_cycle[ah_j], {args});
      end
    end'''
    observer=observer.replace('// PIPELINE_HISTORY_DECL','\n'.join(declarations))
    observer=observer.replace('// PIPELINE_HISTORY_RESET','ah_head=0;ah_count=0;')
    observer=observer.replace('// PIPELINE_HISTORY_SAMPLE','\n'.join(sample))
    observer=observer.replace('// PIPELINE_HISTORY_DUMP',dump)
    return observer,stages


def token_presence(rows: list[dict], stages: list[str], target_pc: str) -> dict:
    result=[]
    for stage in [*stages,'retire']:
        hits=[r['cycle'] for r in rows if r.get(stage+'_valid')=='1' and r.get(stage+'_pc')==target_pc]
        result.append({'stage':stage,'valid_samples':len(hits),
                       'first_cycle':hits[0] if hits else None,'last_cycle':hits[-1] if hits else None})
    return {'target_pc':target_pc,'stages':result,
            'scope':'PC-tag presence only within the retained pre-failure window; repeated loop iterations may share a PC. Absence outside this window and root-cause ownership are unproven.'}
