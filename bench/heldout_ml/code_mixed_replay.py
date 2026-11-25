"""Replay fusion + alert policy on the code-mixed Tamil/Hindi dump. usage: replay_cm.py cm_raw.jsonl [out.json]"""
import sys, json, collections as C
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from sentinel import pipeline as pl
from sentinel.fusion import fuse
from sentinel.alert_policy import evidence_should_alert

rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
assert not any(r['sms_err'] for r in rows), 'sms errors'
for r in rows:
    e = fuse(r['text'], r['sms_result'], r['url_results'], pl._safe_sms_cues(r['text']), None, None)
    r['level'], r['sms_label'], r['alert'], r['risk'] = e.level, e.sms_label, bool(evidence_should_alert(e)), e.risk


def stats(sel):
    tp = sum(r['alert'] for r in sel if r['truth'] == 'risky'); p = sum(r['truth'] == 'risky' for r in sel)
    fp = sum(r['alert'] for r in sel if r['truth'] == 'ham'); n = sum(r['truth'] == 'ham' for r in sel)
    return {'risky': p, 'caught': tp, 'recall_pct': round(100 * tp / p, 1) if p else None,
            'ham': n, 'false_alarms': fp, 'false_alarm_pct': round(100 * fp / n, 1) if n else None}


out = {'rows': len(rows), 'overall': stats(rows)}
for lang in ('Tamil', 'Hindi'):
    out[lang] = stats([r for r in rows if r['language'] == lang])
print(json.dumps(out, indent=1))
cat = {}
for (lang, truth, c), sel in sorted(C.defaultdict(list, {}).items()): pass
g = C.defaultdict(list)
for r in rows: g[(r['language'], r['truth'], r['category'])].append(r)
print('\nwrong by category (language, truth, category): wrong/total, levels, model labels')
for k in sorted(g):
    sel = g[k]; wrong = [r for r in sel if r['alert'] != (r['truth'] == 'risky')]
    cat['|'.join(k)] = {'total': len(sel), 'wrong': len(wrong)}
    if wrong:
        print(f"  {k}: {len(wrong)}/{len(sel)}  levels={dict(C.Counter(r['level'] for r in wrong))} labels={dict(C.Counter(r['sms_label'] for r in wrong))}")
tw = C.Counter(r['id'].rsplit('-', 1)[0] for r in rows if r['alert'] != (r['truth'] == 'risky'))
print('\ntemplates with any wrong:', len(tw), 'of 122; fully wrong (10/10):', sum(v == 10 for v in tw.values()))
out['by_category'] = cat
out['model_label_counts'] = {f"{t}|{l}": n for (t, l), n in sorted(C.Counter((r['truth'], r['sms_label']) for r in rows).items())}
print(out['model_label_counts'])
if len(sys.argv) > 2:
    json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1)
if len(sys.argv) > 3:
    seen = set()
    for r in rows:
        t = r['id'].rsplit('-', 1)[0]
        if r['alert'] != (r['truth'] == 'risky') and t not in seen:
            seen.add(t); print(f"{t} x{tw[t]} {r['truth']} {r['category']} -> {r['level']} {r['sms_label']} risk={r['risk']}\n    {r['text'][:200]}")
