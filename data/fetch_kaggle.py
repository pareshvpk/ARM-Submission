"""Download SMS and URL datasets from data/kaggle_sources.csv and record their licences.

Network/malware sets are only catalogued (multi-GB; used as Kaggle kernel inputs).
Usage: python data/fetch_kaggle.py [--all]   (--all also downloads net/mal)
"""
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
ENV = {"PYTHONIOENCODING": "utf-8"}


def run(args):
    import os
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **ENV})


_REF_RE = re.compile(r"^[\w-]+/[\w-]+$")
_CAT_RE = re.compile(r"^[\w-]+$")


def fetch(row):
    ref, cat = row["ref"], row["cat"]
    if not _REF_RE.match(ref) or "/" in ref.replace("/", "") or "\\" in ref or ".." in ref:
        return ref, cat, "", f"FAIL invalid ref rejected: {ref!r}"
    if not _CAT_RE.match(cat) or cat in (".", "..") or "/" in cat or "\\" in cat:
        return ref, cat, "", f"FAIL invalid cat rejected: {cat!r}"
    dest = (RAW / cat / ref.replace("/", "__")).resolve()
    if not dest.is_relative_to(RAW.resolve()) or dest == RAW.resolve():
        return ref, cat, "", f"FAIL dest escapes RAW: {dest}"
    dest.mkdir(parents=True, exist_ok=True)
    meta = run(["kaggle", "datasets", "metadata", ref, "-p", str(dest)])
    if meta.returncode:
        return ref, cat, "", "FAIL metadata " + (meta.stderr or meta.stdout).strip()[-200:]
    lic = ""
    mfile = dest / "dataset-metadata.json"
    if mfile.exists():
        m = json.loads(mfile.read_text(encoding="utf-8"))
        lic = ";".join(l.get("name", "") for l in m.get("info", m).get("licenses", []))
    if cat in ("sms", "url") or "--all" in sys.argv:
        if not any(p.suffix != ".json" for p in dest.iterdir()):
            r = run(["kaggle", "datasets", "download", ref, "-p", str(dest), "--unzip", "-q"])
            if r.returncode:
                return ref, cat, lic, "FAIL " + (r.stderr or r.stdout).strip()[-200:]
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    return ref, cat, lic, f"ok {size / 1e6:.1f}MB"


rows = list(csv.DictReader(open(ROOT / "kaggle_sources.csv", encoding="utf-8")))
with ThreadPoolExecutor(6) as ex:
    results = list(ex.map(fetch, rows))
with open(ROOT / "kaggle_status.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["ref", "cat", "license", "status"])
    w.writerows(results)
for r in results:
    print(*r, sep=" | ")
