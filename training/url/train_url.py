"""PS3 phishing URL classifier: train on PhiUSIIL, evaluate, export to ExecuTorch.

Runs as a Kaggle script kernel (GPU, internet on). Outputs go to /kaggle/working.
The URL helpers block is a byte-identical copy of sentinel/url_features.py (checked by
tests/test_url_features.py; refresh it with training/sync_shared.py).
"""
import copy
import glob
import inspect
import json
import os
import random
import subprocess
import sys
import textwrap
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split

OUT = "/kaggle/working"
os.makedirs(OUT, exist_ok=True)
_logf = open(f"{OUT}/train_log.txt", "w", encoding="utf-8")


def log(msg):
    print(msg, flush=True)
    _logf.write(str(msg) + "\n")
    _logf.flush()


# --- SENTINEL URL FEATURES BLOCK START ---
import re
from urllib.parse import urlparse

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
# Explicit URLs: scheme (incl. defanged hxxp) or www. prefix.
_EXPLICIT = r"(?:h(?:tt|xx)ps?://|www\.)[^\s<>\"']+"
# Bare domains: labels with no spaces around dots, TLD of 2-24 letters, optional path.
# [.] and (.) are defanged dots.
_DOT = r"(?:\.|\[\.\]|\(\.\))"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_BARE = rf"(?<![\w@.])(?:{_LABEL}{_DOT})+[a-z]{{2,24}}(?![\w-])(?:/[^\s<>\"']*)?"
_URL_RE = re.compile(rf"{_EXPLICIT}|{_BARE}", re.I)
# Common words that look like domains (abbreviations) - not URLs.
_NOT_DOMAINS = {"e.g", "i.e", "a.m", "p.m"}
# Bare domains (no scheme, no www.) need a known TLD, else "ok.See you" reads as a URL.
# ponytail: curated list, swap for the full IANA list if recall on bare domains suffers.
_BARE_TLDS = set((
    "com net org info biz xyz top site online store shop club live app dev io co ai me cc tk ml ga cf gq "
    "buzz link click icu vip win bid loan work fun space website tech pro cloud email support help "
    "in uk us ca au de fr ru cn jp br pk bd lk np ae sg my id ph th vn ng ke za eu ly to gl gd sh"
).split())


def normalise_url(url: str) -> str:
    """Normalise a URL so the model cannot learn the scheme/www/trailing-slash shortcut."""
    if not url or not isinstance(url, str):
        return ""
    url = re.sub(r"^hxxp", "http", url.strip(), flags=re.I)
    url = url.replace("[.]", ".").replace("(.)", ".")
    try:
        parsed = urlparse(url if _SCHEME.match(url) else "http://" + url)
        port = parsed.port
    except ValueError:  # malformed host/port: fall back to plain lowercase text
        return url.lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host + (f":{port}" if port else "")
    if parsed.username:
        netloc = parsed.username + "@" + netloc
    path = parsed.path.rstrip("/")
    query = "?" + parsed.query if parsed.query else ""
    frag = "#" + parsed.fragment if parsed.fragment else ""
    return netloc + path + query + frag


def extract_urls(text: str) -> list:
    """Return URLs found in message text, defanged forms repaired, in order, no duplicates."""
    if not text or not isinstance(text, str):
        return []
    urls = []
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip(".,;:!?)]}'\"")
        u = re.sub(r"^hxxp", "http", u, flags=re.I).replace("[.]", ".").replace("(.)", ".")
        host = re.split(r"[/?#]", re.sub(r"^[a-z]+://", "", u, flags=re.I))[0].lower()
        bare = not re.match(r"^(h(tt|xx)ps?://|www\.)", m.group(0), re.I)
        if host in _NOT_DOMAINS or (bare and host.rsplit(".", 1)[-1] not in _BARE_TLDS):
            continue
        if u not in urls:
            urls.append(u)
    return urls
# --- SENTINEL URL FEATURES BLOCK END ---

SEED, MAX_LEN, BATCH, EPOCHS, PATIENCE, MAX_FPR = 42, 200, 512, 8, 2, 0.02
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.cuda.manual_seed_all(SEED)

# ---- data -------------------------------------------------------------------
csv_files = glob.glob("/kaggle/input/**/PhiUSIIL_Phishing_URL_Dataset.csv", recursive=True)
if not csv_files:
    raise RuntimeError(
        "PhiUSIIL_Phishing_URL_Dataset.csv not found under /kaggle/input "
        "(searched /kaggle/input/**/PhiUSIIL_Phishing_URL_Dataset.csv recursive=True); "
        "check that the dataset is attached to the kernel"
    )
csv = csv_files[0]
df = pd.read_csv(csv, usecols=["URL", "label"])
log(f"loaded {csv}: {len(df)} rows\n{df.label.value_counts()}")
for lab in (0, 1):
    log(f"label {lab} examples: {df[df.label == lab].URL.head(5).tolist()}")
# PhiUSIIL: 1 = legitimate, 0 = phishing. Fail loudly if that ever flips.
assert (df.label == 1).sum() > (df.label == 0).sum(), \
    "label 1 is not the majority class - label meaning may be inverted"
assert df[df.label == 1].URL.str.lower().str.contains("google|facebook|wikipedia|youtube").any(), \
    "no well-known domains under label 1 - label meaning may be inverted"

raw_rows = len(df)
df["norm_url"] = df.URL.map(normalise_url)
df = df[df.norm_url != ""].drop_duplicates("norm_url").reset_index(drop=True)
df["target"] = (df.label == 0).astype(int)  # phishing = positive class
log(f"after normalise+dedup: {len(df)} rows (from {raw_rows})")

trval, test = train_test_split(df, test_size=0.10, random_state=SEED, stratify=df.target)
train, val = train_test_split(trval, test_size=1 / 9, random_state=SEED, stratify=trval.target)
log(f"split train={len(train)} val={len(val)} test={len(test)}")

# Fixed printable-ASCII vocab so the app can rebuild it: 0 pad, 1 unknown.
vocab = {c: i + 2 for i, c in enumerate(map(chr, range(32, 127)))}
VOCAB_SIZE = len(vocab) + 2
json.dump({"pad": 0, "unk": 1, "max_len": MAX_LEN, "chars": vocab}, open(f"{OUT}/vocab.json", "w"))


def encode(urls):
    x = np.zeros((len(urls), MAX_LEN), dtype=np.int64)
    for r, u in enumerate(urls):
        ids = [vocab.get(c, 1) for c in u[:MAX_LEN]]
        x[r, :len(ids)] = ids
    return torch.from_numpy(x)


Xtr, Xva, Xte = encode(train.norm_url), encode(val.norm_url), encode(test.norm_url)
ytr = torch.tensor(train.target.values, dtype=torch.float32)
yva, yte = val.target.values, test.target.values


# ---- model ------------------------------------------------------------------
class URLCNN(nn.Module):
    def __init__(self, vocab_size=97, emb=32, ch=64):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, emb, padding_idx=0)
        self.convs = nn.ModuleList(nn.Conv1d(emb, ch, k, padding=k // 2) for k in (3, 5, 7))
        self.drop = nn.Dropout(0.3)
        self.fc = nn.Linear(ch * 3, 1)

    def forward(self, x):
        h = self.emb(x).transpose(1, 2)
        h = torch.cat([torch.relu(c(h)).amax(dim=2) for c in self.convs], dim=1)
        return self.fc(self.drop(h)).squeeze(1)


assert VOCAB_SIZE == 97
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = URLCNN().to(dev)
n_params = sum(p.numel() for p in model.parameters())
log(f"params={n_params} device={dev}")
assert n_params < 300_000


@torch.no_grad()
def predict(X):
    model.eval()
    return np.concatenate([torch.sigmoid(model(X[i:i + 4096].to(dev))).cpu().numpy()
                           for i in range(0, len(X), 4096)])


def scores(y, p, th):
    yh = (p >= th).astype(int)
    pr, rc, f1, _ = precision_recall_fscore_support(y, yh, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, yh, labels=[0, 1]).ravel()
    return {"precision": float(pr), "recall": float(rc), "f1": float(f1), "fpr": fp / max(fp + tn, 1),
            "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp), "n": int(len(y))}


opt = torch.optim.AdamW(model.parameters(), lr=2e-3)
lossf = nn.BCEWithLogitsLoss()
best_f1, best_state, bad = -1.0, None, 0
for ep in range(1, EPOCHS + 1):
    model.train()
    perm, tot = torch.randperm(len(Xtr)), 0.0
    for i in range(0, len(perm), BATCH):
        idx = perm[i:i + BATCH]
        xb, yb = Xtr[idx].to(dev), ytr[idx].to(dev)
        opt.zero_grad()
        loss = lossf(model(xb), yb)
        loss.backward()
        opt.step()
        tot += loss.item() * len(idx)
    f1 = scores(yva, predict(Xva), 0.5)["f1"]
    log(f"epoch {ep} loss={tot / len(Xtr):.4f} val_f1@0.5={f1:.4f}")
    if f1 > best_f1:
        best_f1, best_state, bad = f1, copy.deepcopy(model.state_dict()), 0
    else:
        bad += 1
        if bad >= PATIENCE:
            log("early stop")
            break
model.load_state_dict(best_state)
model.cpu()
dev = torch.device("cpu")
torch.save(model.state_dict(), f"{OUT}/url_cnn.pt")

# Threshold: best val F1 subject to val FPR <= MAX_FPR.
pva = predict(Xva)
cands = [(scores(yva, pva, t), float(t)) for t in np.linspace(0.05, 0.99, 95)]
ok = [(s["f1"], t) for s, t in cands if s["fpr"] <= MAX_FPR]
th = max(ok)[1] if ok else min(cands, key=lambda c: c[0]["fpr"])[1]
log(f"threshold={th:.2f} (val fpr <= {MAX_FPR} met: {bool(ok)})")

pte = predict(Xte)
test_m = scores(yte, pte, th)
test_m["roc_auc"] = float(roc_auc_score(yte, pte))
has_path = test.norm_url.str.contains("/").values
path_m = scores(yte[has_path], pte[has_path], th)
log(f"TEST {test_m}")
log(f"TEST path-only subset {path_m}")

# Kaggle CPU latency, batch 1. Not the target device; Arm Linux measurements come from bench/.
x1 = Xte[:1]
lat = []
with torch.no_grad():
    for _ in range(50):
        model(x1)
    for _ in range(1000):
        t0 = time.perf_counter()
        model(x1)
        lat.append((time.perf_counter() - t0) * 1e3)
lat_m = {"p50_ms": float(np.percentile(lat, 50)), "p95_ms": float(np.percentile(lat, 95)), "host": "kaggle-cpu"}
log(f"latency {lat_m}")

# Parity inputs for the export step: 500 test URLs and their PyTorch logits.
with torch.no_grad():
    torch.save({"x": Xte[:500], "logits": model(Xte[:500]), "th": torch.tensor(th)}, f"{OUT}/parity_inputs.pt")

metrics = {"seed": SEED, "rows_raw": raw_rows, "rows_dedup": len(df), "train": len(train), "val": len(val),
           "test": len(test), "threshold": th, "params": n_params, "torch": torch.__version__,
           "test_metrics": test_m, "path_only_metrics": path_m, "latency": lat_m}
json.dump(metrics, open(f"{OUT}/metrics.json", "w"), indent=2, default=float)

# ---- ExecuTorch export ------------------------------------------------------
# pip install executorch may replace torch, so export + parity run in a fresh interpreter.
open(f"{OUT}/model_def.py", "w").write("import torch\nimport torch.nn as nn\n\n\n" + inspect.getsource(URLCNN))
EXPORT = textwrap.dedent(f"""
    import importlib.util, json, torch
    from importlib.metadata import version
    from executorch.exir import to_edge_transform_and_lower
    from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
    from executorch.runtime import Runtime
    spec = importlib.util.spec_from_file_location('md', '{OUT}/model_def.py')
    md = importlib.util.module_from_spec(spec); spec.loader.exec_module(md)
    m = md.URLCNN(); m.load_state_dict(torch.load('{OUT}/url_cnn.pt', weights_only=True)); m.eval()  # url_cnn.pt holds a state dict: safe to load with weights_only=True
    par = torch.load('{OUT}/parity_inputs.pt', weights_only=True)  # parity_inputs.pt holds a plain dict of tensors (x, logits, th): safe to load with weights_only=True
    ep = torch.export.export(m, (par['x'][:1],))
    prog = to_edge_transform_and_lower(ep, partitioner=[XnnpackPartitioner()]).to_executorch()
    open('{OUT}/url_cnn.pte', 'wb').write(prog.buffer)
    meth = Runtime.get().load_program('{OUT}/url_cnn.pte').load_method('forward')
    et = torch.cat([meth.execute([par['x'][i:i + 1]])[0] for i in range(len(par['x']))])
    diff = (et - par['logits']).abs().max().item()
    lab = lambda z: (torch.sigmoid(z) >= par['th']).int()
    mism = int((lab(et) != lab(par['logits'])).sum())
    r = dict(executorch=version('executorch'), torch=torch.__version__, max_abs_logit_diff=diff,
             label_mismatches=mism, parity_pass=bool(diff < 1e-3 and mism == 0))
    json.dump(r, open('{OUT}/export.json', 'w'), indent=2)
    print(r)
""")
# Runtime pip install for the export step (S-12): exact versions only, no ranges.
# Index used: PyPI (https://pypi.org/simple) as the primary index via --index-url,
# plus the PyTorch CPU wheel index (https://download.pytorch.org/whl/cpu) as
# --extra-index-url so torch==2.15.0+cpu resolves from the PyTorch index.
PIP_INDEX_URL = "https://pypi.org/simple"
PIP_EXTRA_INDEX_URL = "https://download.pytorch.org/whl/cpu"
# Pinned pair: executorch 1.5.1 pybindings crash ("tensor does not have a device") under Kaggle's
# torch 2.11; verified working with torch 2.15.0+cpu (max logit diff 9.5e-6, 0 mismatches).
pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "executorch==1.5.1", "torch==2.15.0+cpu",
                      "--index-url", PIP_INDEX_URL,
                      "--extra-index-url", PIP_EXTRA_INDEX_URL], capture_output=True, text=True)
log(f"pip install executorch rc={pip.returncode}\n{pip.stderr[-2000:]}")
exp = subprocess.run([sys.executable, "-c", EXPORT], capture_output=True, text=True)
log(f"export rc={exp.returncode}\n{exp.stdout[-2000:]}\n{exp.stderr[-4000:]}")
log("done")
