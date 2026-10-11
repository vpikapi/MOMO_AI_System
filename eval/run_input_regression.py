"""仅十个真实 Qwen 定向场景，复用原 Eval 与生产接口，不跑全量。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import shutil
from concurrent.futures import ThreadPoolExecutor,as_completed
from momo.eval_runner import (ROOT,load_cases,load_config,evaluate_case,check,report,write_json,
    append_json,fingerprint,production_files,now,digest)
from momo.mock_llm import input_capability_mismatch

def main():
    data=ROOT/'eval/eval_dataset_v1_1'
    selected=['mic-014','mic-015','mic-016','mic-021','mic-022','mic-017','mic-018','mic-010','mic-006']
    cases=[r for r in load_cases('micro_action',data) if r['id'] in selected]
    cases += [r for r in json.loads((ROOT/'eval/regression_v2_1.json').read_text(encoding='utf-8'))['new_cases'] if r['id']=='reg-004']
    config=load_config()
    if config.model!='qwen3.8-flash': raise ValueError('本轮需保持 Qwen，不自动切换模型')
    version=fingerprint();run_id=now().replace(':','').replace('-','').replace('.','').replace('+0000','Z')
    out=ROOT/'eval_results'/('input_'+run_id);out.mkdir(parents=True)
    meta=dict(run_id=out.name,evaluation_version='input_fix',started_at=now(),model_name=config.model,temperature=None,
        temperature_policy='not_sent_production_default',selected_count=len(cases),selected_ids=[c['id'] for c in cases],
        categories=['micro_action'],dataset_version='v1_1 unchanged subset + reg-004',prompt_version=version,
        production_files=version,runner_sha256=digest(__file__),workers=4)
    write_json(out/'metadata.json',meta);write_json(out/'cases.json',cases)
    for p in production_files()+[Path(__file__)]:
        dest=out/'snapshot'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    print(out,flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(evaluate_case,c,config,out) for c in cases]):
            r=future.result()
            for s in r['steps']:
                if s['type']!='say': continue
                state=s['state'];a=state.get('micro_action_candidate') or {}
                enabled=a.get('action_type')=='IN_APP' and a.get('input_mode')=='text'
                if r['id'] in ['mic-014','mic-016']:
                    check(r['checks'],'direct text card',True,enabled,enabled)
                    check(r['checks'],'no clarification',False,state['needs_clarification'],not state['needs_clarification'])
                    check(r['checks'],'sufficient context',True,state['context_sufficient'],state['context_sufficient'])
                if a.get('input_mode')=='choice':
                    check(r['checks'],'choice options',True,bool(a['options']),bool(a['options']))
                check(r['checks'],'input capability consistency',False,state['final_response'],not input_capability_mismatch(state['final_response'],enabled),'Prompt')
            r['pass_fail']='PENDING_HUMAN' if all(c['passed'] for c in r['checks']) else 'FAIL'
            append_json(out/'results.jsonl',r)
            print(r['id']+' '+r['pass_fail'],flush=True)
    if version!=fingerprint(): raise RuntimeError('运行中产品版本改变')
    meta['finished_at']=now();write_json(out/'metadata.json',meta);report(out)
    print('COMPLETE '+str(out),flush=True)

if __name__=='__main__': main()
