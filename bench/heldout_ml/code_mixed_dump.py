"""Dump raw model outputs for the code-mixed Tamil/Hindi set so fusion and policy can be replayed offline."""
import sys, json, os, csv
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(str(REPO_ROOT)); sys.path.insert(0, str(REPO_ROOT))
from sentinel import cli, pipeline as pl
OUT = sys.argv[1]
args = cli.build_parser().parse_args(['scan', '--no-llm', '--models-dir', 'models', 'x'])
url_det, sms_det, _, st = cli.load_detectors(args)
assert url_det is not None and sms_det is not None, st
rows = list(csv.DictReader(open(REPO_ROOT / 'bench/heldout_ml/code_mixed_ta_hi_1220.csv', encoding='utf-8-sig', newline='')))
done = sum(1 for _ in open(OUT, encoding='utf-8')) if os.path.exists(OUT) else 0
with open(OUT, 'a', encoding='utf-8') as f:
    for i, r in enumerate(rows):
        if i < done: continue
        t = r['text']
        urls = [pl._score_url_with_detector(u, url_det) for u in pl._extract_urls_safe(t)]
        sms, err = pl._safe_sms_predict_detailed(t, sms_det)
        f.write(json.dumps({**r, 'url_results': urls, 'sms_result': sms, 'sms_err': err}, ensure_ascii=False, default=str) + '\n')
        if i % 200 == 0: f.flush(); print(i, len(rows), flush=True)
print('done', len(rows))
