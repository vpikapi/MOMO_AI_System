"""只读汇总用户提供的 v1 评分；新报告独立保存，不调用模型或改写 v1。"""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'eval_results/20260910T115123410210Z'
SOURCE = Path('C:/Users/pikapi/AppData/Local/Temp/codex-file-preview-aWQy1B/human_scores_示例评分版.csv')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    before = {str(p.relative_to(BASE)): digest(p) for p in BASE.rglob('*') if p.is_file()}
    source_hash = digest(SOURCE)
    with SOURCE.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    with (BASE / 'human_scores.csv').open(encoding='utf-8-sig', newline='') as f:
        originals = {(r['case_id'], r['dimension']): r for r in csv.DictReader(f)}
    keys = [(r['case_id'], r['dimension']) for r in rows]
    assert len(keys) == len(set(keys)) == len(originals)
    for r in rows:
        original = originals[(r['case_id'], r['dimension'])]
        assert all(r[k] == original[k] for k in ('category', 'user_input', 'model_response', 'action_json'))
        if r['score']:
            assert 1 <= float(r['score']) <= 5 and r['reviewer'].strip() and r['reason'].strip()
    records = {r['id']: r for r in (json.loads(l) for l in (BASE / 'graded_results.jsonl').read_text(encoding='utf-8').splitlines())}
    grouped = defaultdict(list)
    for r in rows:
        grouped[r['case_id']].append(r)
    stats = {}
    for cat in ('persona', 'micro_action', 'safety'):
        cat_rows = [r for r in rows if r['category'] == cat]
        dimensions = {}
        for dim in dict.fromkeys(r['dimension'] for r in cat_rows):
            vals = [float(r['score']) for r in cat_rows if r['dimension'] == dim and r['score']]
            dimensions[dim] = {'n': len(vals), 'mean': mean(vals) if vals else None}
        complete_means, six_means, quality_pass = [], [], []
        for case_id, rr in grouped.items():
            if rr[0]['category'] != cat:
                continue
            scores = {r['dimension']: float(r['score']) for r in rr if r['score']}
            required = list(dimensions)
            if cat == 'micro_action' and not json.loads(rr[0]['action_json']):
                required = ['trigger_correct', 'non_pressuring']
            if all(d in scores for d in required):
                complete_means.append(mean(scores[d] for d in required))
                quality_pass.append(all(scores[d] >= 3 for d in required) and all(c['passed'] for c in records[case_id]['checks']))
            if len(scores) == 6:
                six_means.append(mean(scores.values()))
        stats[cat] = {'dimensions': dimensions, 'fully_reviewed_cases': len(complete_means),
                      'complete_case_equal_weight_mean': mean(complete_means),
                      'six_dimension_cases': len(six_means), 'six_dimension_mean': mean(six_means) if six_means else None,
                      'automatic_and_rating_passed': sum(quality_pass)}
    low = [r for r in rows if r['score'] and float(r['score']) <= 2]
    three = [r for r in rows if r['score'] == '3']
    payload = {'source': str(SOURCE), 'source_sha256': source_hash,
               'reviewer_counts': dict(Counter(r['reviewer'] for r in rows)),
               'row_count': len(rows), 'matched_original_rows': len(rows),
               'scored_rows': sum(bool(r['score']) for r in rows),
               'statistics': stats, 'scores_at_most_two': low, 'qualified_score_three': three}
    (HERE / '评分汇总.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    # 临时附件逐字节归档，不重编码、不改分、不覆盖原始运行目录。
    archive = HERE / SOURCE.name
    if archive.exists():
        assert digest(archive) == source_hash
    else:
        archive.write_bytes(SOURCE.read_bytes())
    assert digest(SOURCE) == source_hash
    assert before == {str(p.relative_to(BASE)): digest(p) for p in BASE.rglob('*') if p.is_file()}
    (HERE / '来源与冻结校验.json').write_text(json.dumps({'source_sha256': source_hash,
        'archive_sha256': digest(archive), 'v1_unchanged': True, 'v1_files': before}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'statistics': stats, 'low_rows': len(low), 'low_cases': sorted(set(r['case_id'] for r in low)),
                      'three_rows': len(three), 'v1_unchanged': True}, ensure_ascii=False))

if __name__ == '__main__':
    main()
