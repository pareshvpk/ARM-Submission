import sys, json, re, collections as C
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from sentinel import pipeline as pl
from sentinel.fusion import fuse
from sentinel.alert_policy import evidence_should_alert
tn = lambda i: int(re.search(r'-[hs](\d+)-', i).group(1))
out = C.defaultdict(lambda: [0, 0])
for l in open(sys.argv[1], encoding='utf-8'):
    r = json.loads(l)
    e = fuse(r['text'], r['sms_result'], r['url_results'], pl._safe_sms_cues(r['text']), None, None)
    for k in (('all', r['truth']), ('dev (odd templates)' if tn(r['id']) % 2 else 'test (even templates)', r['truth']), (r['language'], r['truth'])):
        out[k][0] += 1; out[k][1] += bool(evidence_should_alert(e))
for k in sorted(out): print(f"{k[0]:22}{k[1]:6} alert {out[k][1]:4}/{out[k][0]:4} = {100*out[k][1]/out[k][0]:5.1f}%")
