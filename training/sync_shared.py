"""Copy shared helper blocks from sentinel/ into the Kaggle training scripts.

Kaggle uploads only the kernel's code file, so shared code is inlined between markers.
Run after editing sentinel/url_features.py: python training/sync_shared.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S, E = "# --- SENTINEL URL FEATURES BLOCK START ---", "# --- SENTINEL URL FEATURES BLOCK END ---"
SRC = ROOT / "sentinel/url_features.py"
TARGETS = [ROOT / "training/url/train_url.py", ROOT / "training/url_v2/train_url_v2.py"]

src = SRC.read_text(encoding="utf-8")
block = src[src.index(S):src.index(E) + len(E)]
for t in TARGETS:
    text = t.read_text(encoding="utf-8")
    t.write_text(text[:text.index(S)] + block + text[text.index(E) + len(E):], encoding="utf-8")
    print("synced", t.relative_to(ROOT))
