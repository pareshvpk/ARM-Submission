"""PS3 phishing URL classifier v2: unified corpus training, evaluation, and ExecuTorch export.
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
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler

INPUT_DIR = os.environ.get("PS3_INPUT_DIR", "/kaggle/input")
OUT = os.environ.get("PS3_OUT_DIR", "/kaggle/working")
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

# Well-known benign homepages: labelling any of these phishing inverts the corpus.
WELL_KNOWN_BENIGN_DOMAINS = ("google.com", "sbi.co.in", "irctc.co.in", "gov.in")


def _well_known_host(url):
    """Return the bare lowercase host of a normalised URL."""
    s = str(url or "").strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    s = s.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    return s[4:] if s.startswith("www.") else s


def check_well_known_domains_not_phishing(urls, targets, sources):
    """Raise AssertionError if a well-known benign homepage is labelled phishing.

    Args:
        urls: normalised urls loaded from the corpus.
        targets: phishing labels (1 is phishing).
        sources: source file name for each url.

    Raises:
        AssertionError: naming the offending url plus its source.
    """
    bad = []
    for url, target, source in zip(urls, targets, sources):
        if int(target) != 1:
            continue
        host = _well_known_host(url)
        if any(host == d or host.endswith("." + d) for d in WELL_KNOWN_BENIGN_DOMAINS):
            bad.append(f"{url} (source={source})")
    if bad:
        raise AssertionError(
            "well-known benign domain labelled phishing: " + "; ".join(bad[:5])
        )


SEED, MAX_LEN, BATCH, EPOCHS, PATIENCE, MAX_FPR = 42, 200, 1024, 6, 2, 0.01
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.cuda.manual_seed_all(SEED)

# ---- data loading and policy (two-pass memory efficient) --------------------
parquet_files = glob.glob(f"{INPUT_DIR}/**/*.parquet", recursive=True)
if not parquet_files:
    parquet_files = glob.glob(f"{INPUT_DIR}/ps3-corpus/**/*.parquet", recursive=True)
log(f"found {len(parquet_files)} parquet files under {INPUT_DIR}")
if not parquet_files:
    raise RuntimeError(f"no parquet files found under {INPUT_DIR} (also tried {INPUT_DIR}/ps3-corpus); check that ps3-corpus is mounted")

bad_labels = {"phishing", "malicious", "defacement", "malware"}

# Pass 1: find conflict norm_urls (seen with target 0 somewhere and 1 somewhere).
# Vectorised: unique (norm_url, target) pairs per file, then one groupby over all pairs.
pairs = []
for pf in sorted(parquet_files):
    try:
        df_part = pq.read_table(pf, columns=["norm_url", "label"]).to_pandas()
        df_part = df_part[df_part.label.isin(bad_labels | {"benign"}) & (df_part.norm_url.str.len() > 0)]
        df_part = pd.DataFrame({"norm_url": df_part.norm_url.values,
                                "target": df_part.label.isin(bad_labels).astype(np.int8).values}).drop_duplicates()
        pairs.append(df_part)
    except Exception as e:
        log(f"error reading pass 1 {pf}: {e}")
if not pairs:
    raise RuntimeError(f"No parquet file yielded (norm_url,label) pairs from {INPUT_DIR}; pass 1 loaded nothing. Check corpus mount.")
pairs = pd.concat(pairs, ignore_index=True).drop_duplicates()
n_targets = pairs.groupby("norm_url", sort=False)["target"].size()
conflicts_set = set(n_targets.index[n_targets > 1])
n_conflict_urls = len(conflicts_set)
del pairs, n_targets

# Pass 2: load required columns, filter, drop conflicts, dedup per file, apply 400k cap per file, append
capped_dfs = []
raw_rows_total = 0
n_conflict_rows_total = 0

for pf in sorted(parquet_files):
    try:
        avail_cols = pq.read_schema(pf).names
        needed_cols = [c for c in ["norm_url", "label", "source", "host", "registered_domain", "has_path", "url"] if c in avail_cols]
        tbl = pq.read_table(pf, columns=needed_cols)
        df_part = tbl.to_pandas()
        raw_rows_total += len(df_part)
        
        df_part = df_part[df_part.label.isin(bad_labels | {"benign"})].copy()
        if len(df_part) == 0:
            del tbl, df_part
            continue
        
        df_part["target"] = df_part.label.isin(bad_labels).astype(int)
        if "norm_url" not in df_part.columns or df_part.norm_url.isna().all():
            if "url" in df_part.columns:
                df_part["norm_url"] = df_part.url.map(normalise_url)
            else:
                df_part["norm_url"] = ""
        df_part = df_part[df_part.norm_url.str.len() > 0].copy()
        
        if "source" not in df_part.columns:
            df_part["source"] = Path(pf).stem
        
        is_conflict = df_part.norm_url.isin(conflicts_set)
        n_conflict_rows_total += is_conflict.sum()
        df_part = df_part[~is_conflict].copy()
        
        df_part = df_part.drop_duplicates("norm_url").reset_index(drop=True)
        
        if len(df_part) > 400_000:
            df_part = df_part.sample(n=400_000, random_state=SEED).reset_index(drop=True)
        
        log(f"source {Path(pf).stem}: kept {len(df_part)} unique rows (capped at 400k)")
        capped_dfs.append(df_part)
        del tbl, df_part
    except Exception as e:
        log(f"error reading pass 2 {pf}: {e}")

if not capped_dfs:
    raise RuntimeError(f"No parquet datasets loaded from input {INPUT_DIR} in pass 2 (all files failed or empty); aborting")

df = pd.concat(capped_dfs, ignore_index=True).drop_duplicates("norm_url").reset_index(drop=True)
raw_rows = raw_rows_total
n_conflict_rows = n_conflict_rows_total
log(f"total raw rows loaded: {raw_rows}")
log(f"dropped {n_conflict_urls} conflicting norm_urls ({n_conflict_rows} rows) appearing with both target 0 and 1")
log(f"total rows after per-source capping and dedup: {len(df)}")

# F-11: fail loudly if labels are inverted (cf. training/url/train_url.py:113-116).
check_well_known_domains_not_phishing(df.norm_url, df.target, df.source)

# Hosting list exception for group splitting
HOSTING_DOMAINS = {
    "google.com", "googleusercontent.com", "firebaseapp.com", "web.app",
    "blogspot.com", "github.io", "weebly.com", "wixsite.com",
    "000webhostapp.com", "sharepoint.com", "microsoft.com", "live.com",
    "dropbox.com", "ipfs.io", "pages.dev", "vercel.app",
    "netlify.app", "herokuapp.com"
}

if "registered_domain" not in df.columns or df.registered_domain.isna().all():
    def get_reg_domain(h):
        if not h:
            return ""
        parts = h.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else h
    df["registered_domain"] = df.host.map(get_reg_domain)

if "host" not in df.columns:
    df["host"] = ""

# Vectorised split group (F4)
rd = df["registered_domain"].fillna("").str.lower()
h = df["host"].fillna("").str.lower()
is_hosting = rd.isin(HOSTING_DOMAINS) | h.isin(HOSTING_DOMAINS)
hosting_val = np.where(h != "", h, rd)
not_hosting_val = np.where(rd != "", rd, h)
df["split_group"] = np.where(is_hosting, hosting_val, not_hosting_val)

# Group split 80/10/10 by split_group
gss1 = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=SEED)
train_idx, temp_idx = next(gss1.split(df, df.target, groups=df.split_group))
train_df = df.iloc[train_idx].reset_index(drop=True)
temp_df = df.iloc[temp_idx].reset_index(drop=True)

gss2 = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=SEED)
val_idx, test_idx = next(gss2.split(temp_df, temp_df.target, groups=temp_df.split_group))
val_df = temp_df.iloc[val_idx].reset_index(drop=True)
test_df = temp_df.iloc[test_idx].reset_index(drop=True)

log(f"split sizes: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")

# Printable ASCII vocab: 0 pad, 1 unk, max 200 chars
vocab = {c: i + 2 for i, c in enumerate(map(chr, range(32, 127)))}
VOCAB_SIZE = len(vocab) + 2
json.dump({"pad": 0, "unk": 1, "max_len": MAX_LEN, "chars": vocab}, open(f"{OUT}/vocab.json", "w"))


def encode(urls):
    x = np.zeros((len(urls), MAX_LEN), dtype=np.uint8)
    for i, u in enumerate(urls):
        chars = [vocab.get(c, 1) for c in str(u)[:MAX_LEN]]
        x[i, :len(chars)] = chars
    return torch.from_numpy(x)


Xtr, Xva, Xte = encode(train_df.norm_url), encode(val_df.norm_url), encode(test_df.norm_url)
ytr = torch.tensor(train_df.target.values, dtype=torch.float32)
yva, yte = val_df.target.values, test_df.target.values

# Balance training batches roughly 1:1 with WeightedRandomSampler
class_counts = np.bincount(train_df.target.values.astype(int))
class_weights = 1.0 / np.maximum(class_counts, 1)
sample_weights = class_weights[train_df.target.values.astype(int)]
sampler = WeightedRandomSampler(torch.tensor(sample_weights, dtype=torch.double), num_samples=len(sample_weights), replacement=True)

train_dataset = TensorDataset(Xtr, ytr)
train_loader = DataLoader(train_dataset, batch_size=BATCH, sampler=sampler)


# ---- model ------------------------------------------------------------------
class URLCNNv2(nn.Module):
    def __init__(self, vocab_size=97, emb=48, ch=128):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, emb, padding_idx=0)
        self.convs = nn.ModuleList(nn.Conv1d(emb, ch, k, padding=k // 2) for k in (3, 5, 7, 9))
        self.drop = nn.Dropout(0.3)
        self.fc1 = nn.Linear(ch * 4, 256)
        self.fc2 = nn.Linear(256, 1)

    def forward(self, x):
        h = self.emb(x).transpose(1, 2)
        h = torch.cat([torch.relu(c(h)).amax(dim=2) for c in self.convs], dim=1)
        h = torch.relu(self.fc1(self.drop(h)))
        return self.fc2(self.drop(h)).squeeze(1)


assert VOCAB_SIZE == 97
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = URLCNNv2().to(dev)
n_params = sum(p.numel() for p in model.parameters())
log(f"params={n_params} device={dev}")
assert n_params < 600_000


@torch.no_grad()
def predict(X):
    model.eval()
    return np.concatenate([torch.sigmoid(model(X[i:i + 4096].long().to(dev))).cpu().numpy()
                           for i in range(0, len(X), 4096)])


def scores(y, p, th):
    yh = (p >= th).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, yh, labels=[0, 1]).ravel()
    prec, rec, f1, _ = precision_recall_fscore_support(y, yh, average="binary", zero_division=0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return {"precision": float(prec), "recall": float(rec), "f1": float(f1), "fpr": float(fpr),
            "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp), "n": int(len(y))}


opt = torch.optim.AdamW(model.parameters(), lr=2e-3)
lossf = nn.BCEWithLogitsLoss()
best_prauc, best_state, bad = -1.0, None, 0

for ep in range(1, EPOCHS + 1):
    model.train()
    total_loss = 0
    for xb, yb in train_loader:
        xb, yb = xb.long().to(dev), yb.to(dev)
        opt.zero_grad()
        loss = lossf(model(xb), yb)
        loss.backward()
        opt.step()
        total_loss += loss.item() * len(xb)

    pva = predict(Xva)
    prauc = float(average_precision_score(yva, pva))
    log(f"Epoch {ep}/{EPOCHS} loss={total_loss/len(train_df):.4f} val_pr_auc={prauc:.4f}")

    if prauc > best_prauc:
        best_prauc = prauc
        best_state = copy.deepcopy(model.state_dict())
        bad = 0
    else:
        bad += 1
        if bad >= PATIENCE:
            log("Early stopping triggered")
            break

model.load_state_dict(best_state)
model.cpu()
dev = torch.device("cpu")
torch.save(model.state_dict(), f"{OUT}/url_cnn_v2.pt")

# Threshold: best val F1 subject to val FPR <= MAX_FPR.
pva = predict(Xva)
cands = [(scores(yva, pva, t), float(t)) for t in np.linspace(0.05, 0.99, 95)]
ok = [(s["f1"], t) for s, t in cands if s["fpr"] <= MAX_FPR]
th = max(ok)[1] if ok else min(cands, key=lambda c: c[0]["fpr"])[1]
log(f"threshold={th:.2f} (val fpr <= {MAX_FPR} met: {bool(ok)})")

pte = predict(Xte)
test_m = scores(yte, pte, th)
test_m["roc_auc"] = float(roc_auc_score(yte, pte))
test_m["pr_auc"] = float(average_precision_score(yte, pte))
log(f"TEST {test_m}")

# Per source file metrics on test set
test_df["pred_prob"] = pte
test_df["pred_label"] = (pte >= th).astype(int)
per_source_metrics = {}
for src, group in test_df.groupby("source"):
    if len(group) > 0:
        sm = scores(group.target.values, group.pred_prob.values, th)
        per_source_metrics[src] = {"n": sm["n"], "precision": sm["precision"], "recall": sm["recall"], "fpr": sm["fpr"]}
log(f"per source metrics: {per_source_metrics}")

# Per original label recall
per_label_recall = {}
if "label" in test_df.columns:
    for lab, group in test_df[test_df.target == 1].groupby("label"):
        if len(group) > 0:
            rec = float((group.pred_label == 1).mean())
            per_label_recall[lab] = rec
log(f"per label recall (bad classes): {per_label_recall}")

# Subsets evaluation
has_path_mask = test_df.has_path.values if "has_path" in test_df.columns else test_df.norm_url.str.contains("/").values
benign_mask = (test_df.target == 0).values
bad_mask = (test_df.target == 1).values

benign_path_m = scores(yte[benign_mask & has_path_mask], pte[benign_mask & has_path_mask], th) if (benign_mask & has_path_mask).sum() > 0 else {"fpr": 0.0, "n": 0}
benign_bare_m = scores(yte[benign_mask & ~has_path_mask], pte[benign_mask & ~has_path_mask], th) if (benign_mask & ~has_path_mask).sum() > 0 else {"fpr": 0.0, "n": 0}

is_hosted = test_df.host.isin(HOSTING_DOMAINS) | test_df.registered_domain.isin(HOSTING_DOMAINS)
bad_hosted_m = scores(yte[bad_mask & is_hosted], pte[bad_mask & is_hosted], th) if (bad_mask & is_hosted).sum() > 0 else {"recall": 0.0, "n": 0}
bad_not_hosted_m = scores(yte[bad_mask & ~is_hosted], pte[bad_mask & ~is_hosted], th) if (bad_mask & ~is_hosted).sum() > 0 else {"recall": 0.0, "n": 0}

subsets_m = {
    "benign_with_path_fpr": benign_path_m.get("fpr", 0.0),
    "benign_bare_fpr": benign_bare_m.get("fpr", 0.0),
    "bad_hosted_recall": bad_hosted_m.get("recall", 0.0),
    "bad_not_hosted_recall": bad_not_hosted_m.get("recall", 0.0),
}
log(f"subsets metrics: {subsets_m}")

# Indian URLs CSV embedded evaluation
INDIAN_URLS_CSV = """url,label,note
https://www.onlinesbi.sbi/personal/,benign,SBI personal banking login page
https://www.hdfcbank.com/personal/ways-to-bank/online-banking/netbanking,benign,HDFC netbanking page
https://www.icicibank.com/personal-banking/ways-to-bank/internet-banking,benign,ICICI internet banking page
https://www.axisbank.com/bank-smart/internet-banking/features,benign,Axis Bank internet banking
https://www.pnbindia.in/corporate-internet-banking.html,benign,PNB corporate internet banking
https://www.kotak.com/en/personal-banking/ways-to-bank/net-banking.html,benign,Kotak Mahindra net banking
https://www.bankofbaroda.in/ways-to-bank/net-banking,benign,Bank of Baroda net banking
https://www.canarabank.com/en/digital-banking/internet-banking,benign,Canara Bank internet banking
https://www.unionbankofindia.co.in/english/internet-banking.aspx,benign,Union Bank internet banking
https://www.idbibank.in/internet-banking.asp,benign,IDBI Bank internet banking
https://www.indianbank.in/departments/internet-banking/,benign,Indian Bank internet banking
https://www.bankofindia.co.in/internet-banking,benign,Bank of India internet banking
https://www.federalbank.co.in/net-banking,benign,Federal Bank net banking
https://www.yesbank.in/digital-banking/net-banking,benign,Yes Bank net banking
https://www.indusind.com/in/en/personal/ways-to-bank/net-banking.html,benign,IndusInd Bank net banking
https://www.phonepe.com/about/,benign,PhonePe about page
https://paytm.com/about-us,benign,Paytm about page
https://gpay.google.com/,benign,Google Pay info page
https://www.bhimupi.org.in/about-bhim,benign,BHIM UPI about page
https://cred.club/about,benign,CRED about page
https://www.mobikwik.com/about-us,benign,Mobikwik about page
https://www.incometax.gov.in/iec/foportal/,benign,Income Tax Department e-Filing portal
https://uidai.gov.in/en/contact-support/help.html,benign,UIDAI Aadhaar help portal
https://www.digilocker.gov.in/about,benign,DigiLocker about page
https://www.cowin.gov.in/faq,benign,Cowin FAQ page
https://www.india.gov.in/topics/governance,benign,National Portal of India governance topics
https://web.umang.gov.in/landing/,benign,UMANG services portal
https://www.gst.gov.in/about/gst,benign,GST portal about GST
https://www.passportindia.gov.in/AppOnlineProject/welcomeLink,benign,Passport Seva portal
https://www.mygov.in/group/mygov-initiatives/,benign,MyGov initiatives
https://www.nvsp.in/,benign,National Voter Services Portal
https://www.epfindia.gov.in/site_en/index.php,benign,EPFO employee provident fund
https://www.esic.nic.in/about-us,benign,ESIC about us
https://www.irctc.co.in/nget/train-search,benign,IRCTC train ticket booking
https://www.indiapost.gov.in/vas/pages/india-post-home.aspx,benign,India Post home page
https://www.jio.com/selfcare/plans/mobility/prepaid-plans-collection/,benign,Jio prepaid plans
https://www.airtel.in/prepaid-recharge,benign,Airtel prepaid recharge
https://www.myvi.in/prepaid/best-prepaid-plans,benign,Vi prepaid plans
https://www.bsnl.co.in/opencms/bsnl/BSNL/services/mobile/prepaid_plans.html,benign,BSNL prepaid plans
https://www.flipkart.com/helpcentre,benign,Flipkart helpcentre
https://www.amazon.in/gp/help/customer/display.html,benign,Amazon India customer service
https://www.myntra.com/contactus,benign,Myntra contact us
https://www.nykaa.com/help,benign,Nykaa help center
https://www.blinkit.com/faq,benign,Blinkit FAQ
https://www.zeptonow.com/help,benign,Zepto help
https://www.swiggy.com/support,benign,Swiggy support
https://www.zomato.com/help,benign,Zomato help
https://www.tatacliq.com/contact-us,benign,Tata Cliq contact us
https://www.ajio.com/help,benign,Ajio customer care
https://www.reliancedigital.in/content/contact-us,benign,Reliance Digital contact us
https://www.croma.com/contact-us,benign,Croma contact us
https://www.bigbasket.com/help/,benign,BigBasket help
https://www.nseindia.com/market-data/live-equity-market,benign,NSE India market data
https://www.bseindia.com/markets/equity/EQReports/StockPrc.aspx,benign,BSE India stock prices
https://www.rbi.org.in/Scripts/BS_ViewContent.aspx?Id=2009,benign,Reserve Bank of India content
https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doNotAccess=yes,benign,SEBI portal
https://www.isro.gov.in/Mission.html,benign,ISRO missions
https://www.aicte-india.org/about/overview,benign,AICTE overview
https://www.ugc.gov.in/page/About-UGC.aspx,benign,UGC about
https://www.cbse.gov.in/cbsenew/cbse.html,benign,CBSE portal
sbi-kyc-update.xyz/login,phishing,Made-up phishing lookalike pattern
hdfc-reward-point.top/claim,phishing,Made-up phishing lookalike pattern
icici-netbanking-verify.site/auth,phishing,Made-up phishing lookalike pattern
axis-bank-update.xyz/kyc,phishing,Made-up phishing lookalike pattern
paytm-kyc-complete.online/login,phishing,Made-up phishing lookalike pattern
phonepe-cashback-reward.xyz/claim,phishing,Made-up phishing lookalike pattern
gpay-scratch-card.top/win,phishing,Made-up phishing lookalike pattern
income-tax-refund.xyz/claim,phishing,Made-up phishing lookalike pattern
aadhaar-uidai-update.site/verify,phishing,Made-up phishing lookalike pattern
digilocker-document-verify.xyz/login,phishing,Made-up phishing lookalike pattern
irctc-refund-ticket.top/claim,phishing,Made-up phishing lookalike pattern
indiapost-parcel-track.site/delivery,phishing,Made-up phishing lookalike pattern
jio-free-data.xyz/offer,phishing,Made-up phishing lookalike pattern
airtel-5g-upgrade.top/sim,phishing,Made-up phishing lookalike pattern
flipkart-big-billion.xyz/win,phishing,Made-up phishing lookalike pattern
amazon-prize-winner.site/claim,phishing,Made-up phishing lookalike pattern
zomato-free-coupon.top/eat,phishing,Made-up phishing lookalike pattern
swiggy-delivery-bonus.xyz/claim,phishing,Made-up phishing lookalike pattern
zudio-sale-voucher.site/shop,phishing,Made-up phishing lookalike pattern
pnb-account-block.xyz/verify,phishing,Made-up phishing lookalike pattern
kotak-811-activate.top/login,phishing,Made-up phishing lookalike pattern
bob-netbanking-lock.site/unlock,phishing,Made-up phishing lookalike pattern
canara-bank-kyc.xyz/update,phishing,Made-up phishing lookalike pattern
union-bank-verify.top/auth,phishing,Made-up phishing lookalike pattern"""

import io
india_df = pd.read_csv(io.StringIO(INDIAN_URLS_CSV))
india_df["norm_url"] = india_df.url.map(normalise_url)
X_india = encode(india_df.norm_url)
p_india = predict(X_india)
india_df["pred_prob"] = p_india
india_df["pred_label"] = (p_india >= th).astype(int)
india_target = india_df.label.apply(lambda l: 1 if l == "phishing" else 0).values

india_benign = india_df[india_target == 0]
india_phish = india_df[india_target == 1]
india_benign_fpr = float((india_benign.pred_label == 1).mean()) if len(india_benign) > 0 else 0.0
india_phish_recall = float((india_phish.pred_label == 1).mean()) if len(india_phish) > 0 else 0.0

misclassified_india = india_df[india_df.pred_label != india_target][["url", "label", "pred_prob", "note"]].to_dict(orient="records")
log(f"Indian URLs: benign FPR={india_benign_fpr:.4f}, phishing recall={india_phish_recall:.4f}, misclassified={len(misclassified_india)}")
for m in misclassified_india:
    log(f"  Misclassified Indian URL: {m}")

# Save errors.csv: 200 highest-scoring benign test URLs and 200 lowest-scoring bad test URLs
test_df["true_target"] = yte
if "url" not in test_df.columns:
    test_df["url"] = test_df["norm_url"]
benign_test = test_df[test_df.true_target == 0].sort_values("pred_prob", ascending=False).head(200)
bad_test = test_df[test_df.true_target == 1].sort_values("pred_prob", ascending=True).head(200)
errors_df = pd.concat([benign_test, bad_test], ignore_index=True)
errors_df[["url", "norm_url", "label", "true_target", "pred_prob", "source"]].to_csv(f"{OUT}/errors.csv", index=False)
log(f"saved errors.csv with {len(errors_df)} rows")

# Kaggle CPU latency batch 1 p50/p95 (F5: 50 warm-up runs, then 1000 timed runs)
x1 = Xte[:1].long()
lat = []
with torch.no_grad():
    for _ in range(50):
        model(x1.to(dev))
    for _ in range(1000):
        t0 = time.perf_counter()
        model(x1.to(dev))
        lat.append((time.perf_counter() - t0) * 1e3)
lat_m = {"p50_ms": float(np.percentile(lat, 50)), "p95_ms": float(np.percentile(lat, 95)), "host": "kaggle-cpu"}
log(f"latency {lat_m}")

metrics = {
    "seed": SEED,
    "rows_raw": raw_rows,
    "rows_dedup_clean": len(df),
    "train": len(train_df),
    "val": len(val_df),
    "test": len(test_df),
    "threshold": th,
    "params": n_params,
    "torch": torch.__version__,
    "test_metrics": test_m,
    "per_source_metrics": per_source_metrics,
    "per_label_recall": per_label_recall,
    "subsets_metrics": subsets_m,
    "indian_urls_metrics": {
        "benign_fpr": india_benign_fpr,
        "phishing_recall": india_phish_recall,
        "misclassified": misclassified_india,
    },
    "latency": lat_m,
}
json.dump(metrics, open(f"{OUT}/metrics.json", "w"), indent=2, default=float)

# Parity inputs for export step: 500 test URLs and their PyTorch logits
with torch.no_grad():
    torch.save({"x": Xte[:500].long(), "logits": model(Xte[:500].long().to(dev)).cpu(), "th": torch.tensor(th)}, f"{OUT}/parity_inputs.pt")

if os.environ.get("PS3_SKIP_EXPORT") != "1":
    # ---- ExecuTorch export ------------------------------------------------------
    # pip install executorch may replace torch, so export + parity run in a fresh interpreter.
    open(f"{OUT}/model_def.py", "w").write("import torch\nimport torch.nn as nn\n\n\n" + inspect.getsource(URLCNNv2))
    EXPORT = textwrap.dedent(f"""
        import importlib.util, json, torch
        from importlib.metadata import version
        from executorch.exir import to_edge_transform_and_lower
        from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
        from executorch.runtime import Runtime
        spec = importlib.util.spec_from_file_location('md', '{OUT}/model_def.py')
        md = importlib.util.module_from_spec(spec); spec.loader.exec_module(md)
        m = md.URLCNNv2(); m.load_state_dict(torch.load('{OUT}/url_cnn_v2.pt', weights_only=True)); m.eval()  # url_cnn_v2.pt holds a state dict: safe to load with weights_only=True
        par = torch.load('{OUT}/parity_inputs.pt', weights_only=True)  # parity_inputs.pt holds a plain dict of tensors (x, logits, th): safe to load with weights_only=True
        ep = torch.export.export(m, (par['x'][:1],))
        prog = to_edge_transform_and_lower(ep, partitioner=[XnnpackPartitioner()]).to_executorch()
        open('{OUT}/url_cnn_v2.pte', 'wb').write(prog.buffer)
        meth = Runtime.get().load_program('{OUT}/url_cnn_v2.pte').load_method('forward')
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
