"""只读取 v1，比较 v2 保存输出；导出空白评分表，不重用旧人工分数。"""
import argparse
import copy
import csv
import json
from pathlib import Path
from .eval_runner import read_jsonl, write_json, summarize, check_turn

def compare(run, baseline):
    old_meta=json.loads((baseline/'metadata.json').read_text(encoding='utf-8'))
    new_meta=json.loads((run/'metadata.json').read_text(encoding='utf-8'))
    model_changed=old_meta['model_name']!=new_meta['model_name']
    old=read_jsonl(baseline/'graded_results.jsonl')
    new=read_jsonl(run/'graded_results.jsonl')
    old_by={r['id']:r for r in old}
    # 同一输入按原始断言再计一次，避免把标签修订计为修复收益。
    common=[]
    for record in new:
        original=old_by.get(record['id'])
        if not original: continue
        r=copy.deepcopy(record)
        if record['category']!='intent':
            original_steps=[s for s in original['case']['steps'] if s['type']=='say']
            turns=[s for s in r['steps'] if s['type']=='say']
            assert [s['text'] for s in turns]==[s['text'] for s in original_steps]
            if record['id'] in ('mic-015','saf-018'):
                # 这两条是单轮、无最终数据库断言的标签变更案例。
                r['checks']=[]
                for step,turn in zip(original_steps,turns):
                    turn['expect']=step.get('expect',{})
                    check_turn(r['checks'],step,turn)
        common.append(r)
    assert len(common)==len(old), '必须完成全部共同案例后才能输出比较'
    old_metrics=json.loads((baseline/'metrics.json').read_text(encoding='utf-8'))
    new_metrics=json.loads((run/'metrics.json').read_text(encoding='utf-8'))
    common_metrics=summarize(common)
    regressions=[];improvements=[]
    for r in common:
        before=all(c['passed'] for c in old_by[r['id']]['checks'])
        after=all(c['passed'] for c in r['checks'])
        if before and not after: regressions.append(r['id'])
        if after and not before: improvements.append(r['id'])
    write_json(run/'comparison.json',dict(baseline_model=old_meta['model_name'],current_model=new_meta['model_name'],model_changed=model_changed,
        comparison_scope='跨模型观察，不归因于代码修复' if model_changed else '同模型单次回归观察',
        v1=old_metrics,v2_original_labels_common_cases=common_metrics,
        v2_new_labels_all_cases=new_metrics,automatic_regressions=regressions,automatic_improvements=improvements,
        note='主观维度待 v2 新评分；自动通过不代表 Persona/行动质量通过'))
    with (baseline/'human_scores.csv').open(encoding='utf-8-sig',newline='') as f:
        old_scores={(r['case_id'],r['dimension']):r for r in csv.DictReader(f)}
    with (run/'human_scores.csv').open(encoding='utf-8-sig',newline='') as f:
        source=list(csv.DictReader(f))
    columns=list(source[0])+['response_unchanged','action_unchanged','input_unchanged']
    for row in source:
        prior=old_scores.get((row['case_id'],row['dimension']))
        for key in ('score','reason','reviewer','reviewed_at'): row[key]=''
        for key,field in [('response_unchanged','model_response'),('action_unchanged','action_json'),('input_unchanged','user_input')]:
            row[key]=str(bool(prior and prior[field]==row[field])).lower()
    target=run/'human_scores_v2_pending.csv'
    if target.exists(): raise FileExistsError('不覆盖可能已有新评分的 v2 文件')
    with target.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(source)
    rows=['# MOMO Eval v1 → Fix → Eval v2','',
          f"真实模型：{new_meta['model_name']}；基线模型：{old_meta['model_name']}。"+('本次是跨模型观察，分数差不能单独归因于代码修复。' if model_changed else ''),
          'v1 的用户提供评分来源为 ChatGPT_draft，保持冻结。v2 尚未重新评分。',
          'v1 共134场景，v2共136场景。原标签共同集用于对比修复；新标签全量成绩单列。','',
          '| 指标 | v1 | v2 原标签共同集 | v2 新标签全量 |','|---|---:|---:|---:|']
    for title,cat,key in [('Intent Accuracy','intent','accuracy'),('Memory 自动通过率','memory','automatic_pass_rate'),
        ('Micro Action 自动通过率','micro_action','automatic_pass_rate'),('Safety Recall','safety','recall'),
        ('Safety FP','safety','false_positive_count'),('Safety FN','safety','false_negative_count')]:
        rows.append(f'| {title} | {old_metrics[cat][key]} | {common_metrics[cat][key]} | {new_metrics[cat][key]} |')
    rows+=['| Persona 主观均分 | 4.07/5 | 待评分 | 待评分 |','| Micro Action 主观均分 | 4.70/5 | 待评分 | 待评分 |','',
           '自动改善案例：'+(', '.join(improvements) or '无'),'自动回归案例：'+(', '.join(regressions) or '无'),'',
           '## 重点案例的原始内容','']
    focus=('mem-018','mem-008','saf-019','mic-016','mem-023','per-020','saf-030','int-019','mic-015','saf-018','mic-021','mic-022')
    for case in focus:
        r=next((r for r in new if r['id']==case),None)
        if not r: continue
        rows += [f'### {case}', '', '自动状态：'+r['pass_fail']]
        for step in r['steps']:
            if step['type']!='say': continue
            s=step['state']
            rows += ['', '用户：'+step['text'],'', '回复：'+s['final_response'],'',
                '状态：'+json.dumps({k:s.get(k) for k in ('risk_level','safety_subject','action_requested','context_sufficient',
                    'micro_action_block_reason','action_type','memory_suppressed','memory_rejection_reason')},ensure_ascii=False)]
        if r.get('actual_memory_state'):
            rows += ['','确认后记忆：'+json.dumps([{k:x.get(k) for k in ('kind','slot','content')} for x in r['actual_memory_state']],ensure_ascii=False)]
    rows += ['', '## 限制','',
        '本轮每场景一次，供应商默认温度未传，模型别名可能变化。自动断言使用部分字符串代理，失败需复核全文。界面机制有离线回归测试，真实评测脚本没有操作浏览器。',
        'saf-018 的原输出已为 High，标签修订本身不算修复。mic-015 新定义允许一次必要澄清，新增两条多轮场景单独验证。',
        'human_scores_v2_pending.csv 的 score/reason 留空；response_unchanged 只表示逐字相同，不表示可以自动复用旧分数。',
        '本轮没有根据 v2 分数继续自动优化。失败原文和断言保留在 results.jsonl、failures.jsonl。']
    (run/'v1_vs_v2.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path)
    p.add_argument('--baseline',type=Path,default=Path(__file__).resolve().parents[1]/'eval_results/20260910T115123410210Z')
    a=p.parse_args();compare(a.run.resolve(),a.baseline.resolve())

if __name__=='__main__': main()
