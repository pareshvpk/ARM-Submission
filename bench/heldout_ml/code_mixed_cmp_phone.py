"""Compare phone dry-run verdicts with the PC replay. usage: cmp_phone.py cm_raw.jsonl phone.log [out.json]"""
import sys, json, re, collections as C
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from sentinel import pipeline as pl
from sentinel.fusion import fuse
from sentinel.alert_policy import evidence_should_alert
rows = {}
for l in open(sys.argv[1], encoding='utf-8'):
    r = json.loads(l)
    e = fuse(r['text'], r['sms_result'], r['url_results'], pl._safe_sms_cues(r['text']), None, None)
    r['pc'] = (e.level, e.sms_label, bool(evidence_should_alert(e)), e.risk); rows[r['id']] = r
pat = re.compile(r'debug_verdict id=(\S+) level=(\S+) sms_label=(\S+) risk=(\S+) alert=(\S+)')
ph = {}
for l in open(sys.argv[2], encoding='utf-8', errors='replace'):
    m = pat.search(l)
    if m: ph[m.group(1)] = (m.group(2), m.group(3), m.group(5) == 'true', float(m.group(4)))
assert set(ph) == set(rows), (len(ph), len(rows))
def stats(sel):
    p = [r for r in sel if r['truth'] == 'risky']; n = [r for r in sel if r['truth'] == 'ham']
    tp = sum(ph[r['id']][2] for r in p); fp = sum(ph[r['id']][2] for r in n)
    return {'risky': len(p), 'caught': tp, 'recall_pct': round(100*tp/len(p), 1), 'ham': len(n), 'false_alarms': fp, 'false_alarm_pct': round(100*fp/len(n), 1)}
out = {'device': 'Galaxy M31 SM-M315F, sms_fp32.pte', 'rows': len(ph), 'overall': stats(rows.values())}
for lang in ('Tamil', 'Hindi'): out[lang] = stats([r for r in rows.values() if r['language'] == lang])
d_alert = [i for i in rows if rows[i]['pc'][2] != ph[i][2]]; d_level = [i for i in rows if rows[i]['pc'][0] != ph[i][0]]
d_label = [i for i in rows if rows[i]['pc'][1] != ph[i][1]]
dr = sorted(abs(rows[i]['pc'][3] - ph[i][3]) for i in rows)
out['vs_pc_int8'] = {'alert_differs': len(d_alert), 'level_differs': len(d_level), 'model_label_differs': len(d_label),
                     'risk_abs_diff_median': round(dr[len(dr)//2], 4), 'risk_abs_diff_max': round(dr[-1], 4)}
print(json.dumps(out, indent=1))
for i in d_alert: print(' alert differs', i, rows[i]['truth'], 'pc', rows[i]['pc'], 'phone', ph[i])
if len(sys.argv) > 3: json.dump(out, open(sys.argv[3], 'w', encoding='utf-8'), indent=1)
