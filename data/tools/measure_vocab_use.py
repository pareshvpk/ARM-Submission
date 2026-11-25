"""How much of the kept SMS vocabulary is used? Token frequency on a corpus sample, UNK rate on eval text at smaller vocabularies."""
import json, glob, collections, csv, sys, random
from pathlib import Path
import pandas as pd
from tokenizers import Tokenizer
ROOT = Path(__file__).resolve().parents[2]
R = str(ROOT)
tok = Tokenizer.from_file(str(ROOT / 'models/sms_v6ml/tokenizer/tokenizer.json')); tok.no_padding(); tok.no_truncation()
kept = set(json.load(open(ROOT / 'models/sms_v6ml/kept_tokens.json')))
random.seed(0)
freq = collections.Counter(); rows = 0
files = sorted(glob.glob(str(ROOT / 'data/processed/sms/*.parquet'))) + sorted(glob.glob(str(ROOT / 'data/processed_ml/sms/*.parquet')))
for f in files:
    try: t = pd.read_parquet(f, columns=['text'])['text'].dropna().astype(str)
    except Exception as e: print('skip', f, e); continue
    if len(t) > 15000: t = t.sample(15000, random_state=0)
    for enc in tok.encode_batch(list(t)):
        freq.update(enc.ids); rows += 1
print('corpus sample rows', rows, 'files', len(files), 'distinct tokens', len(freq), 'in kept', len(set(freq) & kept), 'token occurrences', sum(freq.values()))
ranked = [t for t, _ in freq.most_common()]
ev = {}
h = pd.read_csv(ROOT / 'bench/heldout/heldout_20261107.csv')
for lang, g in h.groupby('language'): ev['heldout_' + lang] = list(g.text.astype(str))
cm = list(csv.DictReader(open(ROOT / 'bench/heldout_ml/code_mixed_ta_hi_1220.csv', encoding='utf-8-sig')))
ev['code_mixed_Tamil'] = [r['text'] for r in cm if r['language'] == 'Tamil']; ev['code_mixed_Hindi'] = [r['text'] for r in cm if r['language'] == 'Hindi']
for n, f in (('inbox_vivo', 'real_sms_vivo.csv'), ('inbox_m31', 'real_sms.csv'), ('inbox_f14', 'real_sms_f14.csv')):
    ev[n] = list(pd.read_csv(ROOT / 'bench/heldout_ml' / f).text.astype(str))
enc = {k: [e.ids for e in tok.encode_batch(v)] for k, v in ev.items()}
lens = sorted(len(i) for v in enc.values() for i in v)
if lens:
    print('token length all eval: p50', lens[len(lens)//2], 'p90', lens[int(len(lens)*.9)], 'p99', lens[int(len(lens)*.99)], 'max', lens[-1], 'share>128', round(sum(l > 128 for l in lens)/len(lens), 4), 'share>64', round(sum(l > 64 for l in lens)/len(lens), 4))
else:
    print('token length all eval: empty')
print('vocab_size | corpus coverage | per-set: token UNK % / messages with any UNK %')
for n in (79017, 60000, 50000, 40000, 30000, 20000):
    v = kept if n == 79017 else set(ranked[:n]) | {0, 1, 2, 3}
    cov = sum(c for t, c in freq.items() if t in v) / sum(freq.values())
    parts = []
    for k, L in enc.items():
        tot = sum(len(i) for i in L); unk = sum(1 for i in L for t in i if t not in v); anyu = sum(any(t not in v for t in i) for i in L)
        parts.append(f"{k} {100*unk/tot:.2f}/{100*anyu/len(L):.1f}")
    print(n, f"{100*cov:.3f}%", ' | '.join(parts))
