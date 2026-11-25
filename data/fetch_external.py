"""Download non-Kaggle datasets (Hugging Face, GitHub, Mendeley, live feeds) into data/raw/ext/.

Live feeds (OpenPhish, URLhaus, Tranco) are snapshots: the file name carries today's date.
PhreshPhish (732 GB with HTML) is NOT downloaded here; only its URL column is needed - see docs/datasets.md.
Usage: .venv/Scripts/python data/fetch_external.py
"""
import datetime
import hashlib
import io
import json
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download

OUT = Path(__file__).resolve().parent / "raw" / "ext"
TODAY = datetime.date.today().isoformat()
UA = {"User-Agent": "arm-ps3-dataset-fetch (research)"}

HF = [
    "ucirvine/sms_spam", "Ridham115/indian-scam-sms-synthetic-audited", "bolewara/hinglish-scam-text-dataset",
    "nini654/hinglish-scam-text-dataset", "karanverma19/Indian_Multilingual_Scam_Message_Dataset",
    "alusci/sms-otp-spam-dataset", "CloveAI/india-spam-sms", "MOZNLP/MOZ-Smishing",
    "ysangam/Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset", "dbarbedillo/SMS_Spam_Multilingual_Collection_Dataset",
    "pirocheto/phishing-url",
]
# TODO: commit hashes are unknown offline. Replace each "TODO-pin-to-commit-hash"
# value below with the actual snapshot commit hash for that repo before running
# this script; snapshot_download is pinned with revision=HF_REVISIONS[repo] so a
# silently updated or hijacked upstream repo cannot change content between runs.
HF_REVISION = "TODO-pin-to-commit-hash"
HF_REVISIONS = {
    "ucirvine/sms_spam": HF_REVISION,
    "Ridham115/indian-scam-sms-synthetic-audited": HF_REVISION,
    "bolewara/hinglish-scam-text-dataset": HF_REVISION,
    "nini654/hinglish-scam-text-dataset": HF_REVISION,
    "karanverma19/Indian_Multilingual_Scam_Message_Dataset": HF_REVISION,
    "alusci/sms-otp-spam-dataset": HF_REVISION,
    "CloveAI/india-spam-sms": HF_REVISION,
    "MOZNLP/MOZ-Smishing": HF_REVISION,
    "ysangam/Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset": HF_REVISION,
    "dbarbedillo/SMS_Spam_Multilingual_Collection_Dataset": HF_REVISION,
    "pirocheto/phishing-url": HF_REVISION,
}
GIT = {"SMISH_DT": "https://github.com/MarazMia/SMISH_DT",
       "reportsmishing": "https://github.com/reportsmishing/reportsmishing.github.io"}
FEEDS = {
    f"openphish_feed_{TODAY}.txt": "https://openphish.com/feed.txt",
    f"urlhaus_recent_{TODAY}.csv": "https://urlhaus.abuse.ch/downloads/csv_recent/",
    f"tranco_top1m_{TODAY}.zip": "https://tranco-list.eu/top-1m.csv.zip",
}
MENDELEY = {"mishra_soni_smishing": "f45bkkt8pr", "url_phish_2025": "vfszbj9b36"}

FEED_MANIFEST_NAME = "sha256_manifest.txt"


def safe_dest(base: Path, filename: str) -> Path:
    """Resolve ``filename`` inside ``base``, rejecting path traversal.

    Rejects (with ValueError) a name that is absolute, contains a path
    separator or ``..``, or whose resolved path would escape ``base``.
    Used for every name that comes from an API response or a remote listing.
    """
    if not isinstance(filename, str) or not filename:
        raise ValueError(f"invalid filename: {filename!r}")
    if Path(filename).is_absolute():
        raise ValueError(f"absolute filename rejected: {filename!r}")
    if "/" in filename or "\\" in filename:
        raise ValueError(f"filename contains a path separator: {filename!r}")
    if ".." in Path(filename).parts or filename in (".", ".."):
        raise ValueError(f"filename contains '..': {filename!r}")
    base_resolved = Path(base).resolve()
    target = (base_resolved / filename).resolve()
    if not target.is_relative_to(base_resolved):
        raise ValueError(f"filename resolves outside destination: {filename!r}")
    return target


validate_filename = safe_dest
resolve_safe_path = safe_dest


MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def download_to_file(url, dest: Path) -> str:
    """Stream a URL to dest, returning its SHA-256 hex digest.

    Reads in chunks so a large upstream file is never buffered fully in
    RAM, hashing incrementally as it writes. Raises if the file exceeds
    MAX_DOWNLOAD_BYTES.
    """
    dest = Path(dest)
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as response:
        with open(dest, "wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    try:
                        handle.close()
                    except Exception:
                        pass
                    try:
                        dest.unlink()
                    except Exception:
                        pass
                    raise ValueError(f"download exceeds {MAX_DOWNLOAD_BYTES} bytes: {url}")
                digest.update(chunk)
                handle.write(chunk)
    return digest.hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_feed_manifest(feed_hashes: dict, feeds_dir: Path = None) -> Path:
    """Write a SHA-256 manifest of the downloaded feeds next to them.

    One ``<sha256>  <filename>`` line per feed, sorted by filename, in
    ``sha256_manifest.txt`` inside the feeds directory.
    """
    feeds_dir = Path(feeds_dir) if feeds_dir is not None else OUT / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = feeds_dir / FEED_MANIFEST_NAME
    lines = [f"{feed_hashes[name]}  {name}" for name in sorted(feed_hashes)]
    manifest_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return manifest_path


def step(name, fn):
    try:
        fn()
        print("ok  ", name)
    except Exception as e:  # keep going; report at the end
        print("FAIL", name, type(e).__name__, str(e)[:200])


def main():
    feed_hashes: dict = {}
    for repo in HF:
        step(f"hf {repo}", lambda r=repo: snapshot_download(
            r, repo_type="dataset", revision=HF_REVISIONS[r],
            local_dir=safe_dest(OUT / "hf", r.replace("/", "__"))))
    for name, url in GIT.items():
        dest = safe_dest(OUT / "git", name)
        step(f"git {name}", lambda u=url, d=dest: d.exists() or subprocess.run(
            ["git", "clone", "--depth", "1", u, str(d)], check=True, capture_output=True))
    for name, url in FEEDS.items():
        dest = safe_dest(OUT / "feeds", name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        def fetch_feed(u=url, d=dest, n=name):
            feed_hashes[n] = download_to_file(u, d)

        step(f"feed {name}", fetch_feed)
    write_feed_manifest(feed_hashes, OUT / "feeds")
    for name, did in MENDELEY.items():
        def mendeley(n=name, i=did):
            dest = safe_dest(OUT / "mendeley", n)
            dest.mkdir(parents=True, exist_ok=True)
            files = json.loads(get(f"https://data.mendeley.com/public-api/datasets/{i}/files?folder_id=root&version=1"))
            for f in files:
                try:
                    target = safe_dest(dest, f["filename"])
                except (ValueError, KeyError, TypeError) as e:
                    print(f"skip  mendeley {n}: rejected filename {f.get('filename')!r} ({e})")
                    continue
                download_to_file(f["content_details"]["download_url"], target)
        step(f"mendeley {name}", mendeley)


if __name__ == "__main__":
    main()
