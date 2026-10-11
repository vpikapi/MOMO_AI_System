"""比较同模型的原标签交集，归档评分来源；绝不复制旧分数到新回复。"""
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'eval_results/20260910T192946752247Z'
SOURCE=Path('C:/Users/pikapi/AppData/Local/Temp/codex-file-preview-29OELN/human_scores_v2_重新评分.csv')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
def dump(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def passed(r): return all(c['passed'] for c in r['checks'])
def main():
    out=Path(sys.argv[1]).resolve()
    meta=json.loads((out/'metadata.json').read_text(encoding='utf-8'))
    if not meta.get('finished_at'): raise ValueError('等待完整回归结束后汇总')
    baseline={r['id']:r for r in rows(BASE/'graded_results.jsonl')}
    current={r['id']:r for r in rows(out/'graded_results.jsonl')}
    common=sorted(set(baseline)&set(current));new=sorted(set(current)-set(baseline))
    if any(baseline[i]['case']!=current[i]['case'] for i in common): raise ValueError('原标签或输入发生变化')
    archive=out/'source_review';archive.mkdir(exist_ok=True)
    source=SOURCE if SOURCE.exists() else archive/SOURCE.name
    if source!=archive/SOURCE.name: shutil.copy2(source,archive/SOURCE.name)
    with source.open(encoding='utf-8-sig',newline='') as f: reviews=list(csv.DictReader(f))
    old_review={(r['case_id'],r['dimension']):r for r in reviews}
    with (out/'human_scores.csv').open(encoding='utf-8-sig',newline='') as f: pending=list(csv.DictReader(f))
    for r in pending:
        old=old_review.get((r['case_id'],r['dimension']))
        r['response_changed']='false' if old and old['model_response']==r['model_response'] else 'true'
        r['action_changed']='false' if old and old['action_json']==r['action_json'] else 'true'
        r['baseline_available']='true' if old else 'false'
        for k in ['score','reason','reviewer','reviewed_at']: r[k]=''
    with (out/'human_scores_v2_1_pending.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(pending[0]));w.writeheader();w.writerows(pending)
    values=defaultdict(list);dimensions=defaultdict(list)
    for r in reviews:
        if r['score'].strip() in ['1','2','3','4','5']:
            v=int(r['score']);values[r['category']].append(v);dimensions[(r['category'],r['dimension'])].append(v)
    review_summary={'rows':len(reviews),'reviewers':dict(Counter(r['reviewer'] for r in reviews)),
        'category_pooled_means':{c:sum(v)/len(v) for c,v in values.items()},
        'dimensions':{c+'.'+d:{'n':len(v),'mean':sum(v)/len(v)} for (c,d),v in dimensions.items()}}
    dump(out/'v2_review_summary.json',review_summary)
    comparison={}
    for cat in ['intent','memory','persona','micro_action','safety']:
        ids=[i for i in common if current[i]['category']==cat]
        comparison[cat]={'n':len(ids),'before_pass':sum(passed(baseline[i]) for i in ids),'after_pass':sum(passed(current[i]) for i in ids),
            'recovered':[i for i in ids if not passed(baseline[i]) and passed(current[i])],
            'regressions':[i for i in ids if passed(baseline[i]) and not passed(current[i])],
            'remaining_failures':[i for i in ids if not passed(current[i])]}
    turns=[s['state'] for r in current.values() for s in r['steps'] if s.get('type')=='say']
    sources=Counter(s.get('fallback_source') or s.get('capability_truth',{}).get('response_source') or ('safety_template' if 'safety_response_node' in s['trace'] else 'real_llm_or_intent_only') for s in turns)
    changed={i:{'before':[s.get('state',{}).get('final_response','') for s in baseline[i]['steps'] if s['type']=='say'],
                'after':[s.get('state',{}).get('final_response','') for s in current[i]['steps'] if s['type']=='say']} for i in ['per-018','mic-010','mic-011','saf-015','saf-030','mem-018','mem-023','mic-016']}
    dump(out/'comparison_v2_1.json',dict(baseline=BASE.name,current=out.name,common_count=len(common),new_ids=new,
        categories=comparison,response_sources=dict(sources),play_retries=sum(s.get('play_retry_count',0) for s in turns),key_cases=changed))
    v1=ROOT/'eval_results/20260910T115123410210Z'
    frozen=json.loads((ROOT/'eval_analysis/20260911_v1_human_review/来源与冻结校验.json').read_text(encoding='utf-8'))['v1_files']
    dump(out/'provenance.json',{'review_source_sha256':sha(source),'review_archive_sha256':sha(archive/SOURCE.name),
        'v1_frozen_files_unchanged':all(sha(v1/p)==h for p,h in frozen.items()),
        'original_cases_unchanged':True,'source_review_not_independent_human':True,
        'v2_baseline_hashes':{p.name:sha(p) for p in BASE.iterdir() if p.is_file()},
        'new_scores_all_blank':all(not r['score'] and not r['reason'] for r in pending)})
    lines=['# MOMO 小范围 Fix + Regression Eval v2.1','',f'模型：{meta["model_name"]}。同模型 Qwen v2 对照；原标签交集 {len(common)} 个，新增 {len(new)} 个。','',
        '原人工评分：Persona 4.16、Micro Action 4.85、Safety 4.86；保留原评分与理由。评分者标识为 ChatGPT_draft_v2，不称为独立用户评审。新输出全部待重新评分。','',
        '| 原固定集交集 | v2 通过 | v2.1 通过 | 恢复 | 新失败 |','|---|---|---|---|---|']
    for c,v in comparison.items(): lines.append(f'| {c} | {v["before_pass"]}/{v["n"]} | {v["after_pass"]}/{v["n"]} | {", ".join(v["recovered"]) or "—"} | {", ".join(v["regressions"]) or "—"} |')
    lines += ['', '表中为案例全部自动断言通过，不是人工质量分；Persona 仅表示回复完整、无服务中断。Safety Recall / FP / FN 见 summary.md，分类全符合率与保护召回分开解释。', '',
        '## 新增回归','',f'自动通过 {sum(passed(current[i]) for i in new)}/{len(new)}；故意注入 Play 缺字段与文本失败属于单元测试，不混入真实 LLM 分数。', '',
        '## 重点样本','']
    for i,v in changed.items():
        lines += [f'### {i}', '', '修复前：'+' / '.join(v['before']), '', '修复后：'+' / '.join(v['after']), '']
    lines += ['## 解释限制','',
        '- 相同模型、同标签单次回归可说明本次观察到的收益，不能严格隔离模型随机性和代码因果收益。温度维持生产默认，未向接口新增温度参数。',
        '- 待确认说明使用固定产品文案；普通陪伴仍由真实 LLM 生成。Play 若使用本地备用文本单独标注，不计为模型生成成功。',
        '- 正文能力承诺校验为有限中文表达匹配，不是完整语义证明；有行动卡片或已知待确认候选时，正文先校验再展示，其他普通回复继续流式。',
        '- 敏感性依赖模型标记、槽位与本地保护词；异常或缺失敏感性不保存，但无法承诺穷尽所有隐晦敏感表达。',
        '- 二次确认通过 Streamlit AppTest 与实际 SQLite 门槛验证；真实 Eval 的确认步骤模拟已完成两次用户操作，不代表真人实际点击。',
        '- LangGraph 架构、供应商、SQLite、冻结关系成长与 Safety Lock 保持；未新增成长算法、登录或向量库。',
        '- saf-030 原来已为完整首轮加简短后续，本次保留保护；不为评分降低风险或提前解锁。',
        '- 新回复人工评分见 human_scores_v2_1_pending.csv；response_changed 与 action_changed 只比较内容，不复制旧分数。',
        '', '本轮到此停止自动扩展。剩余失败先列出，等待确认是否进入下一轮修复或项目收尾。']
    (out/'Regression_v2_1_说明.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'eval/unit_v2_1.log',out/'unit_tests.log')
    print(json.dumps(dict(comparison=comparison,sources=dict(sources),new_pass=sum(passed(current[i]) for i in new),pending_rows=len(pending)),ensure_ascii=True))

if __name__=='__main__': main()
