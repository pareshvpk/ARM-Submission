"""Score SMS model arms on the held-out and golden sets with the shipped fusion.

Usage (needs torch + transformers; run with the training environment):
    python bench/heldout_ml/score_arms.py NAME=MODEL_DIR[,ID_MAP_JSON] [NAME=...] --out docs/multilang/arms_x

MODEL_DIR holds `sms_model/` and `tokenizer/`. When ID_MAP_JSON is given the input ids are
remapped through it (the pruned-vocabulary path the device uses).

Held-out rows (H): the model probabilities replace the dumped ones; cues and URL values come
from the 2026-11-08 dump; levels come from the real sentinel.fusion.fuse() (shipped rules).
Golden rows (G) and the phone test messages go through sentinel.pipeline.analyse() with the
arm as SMS detector and no URL model (the pipeline's URL-indicator fallback), same for every arm.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

import dump_probs  # noqa: E402
import sim_script_gate as sim  # noqa: E402
from sentinel.pipeline import analyse  # noqa: E402

LANGS = ("English", "Hinglish", "Tamil", "Hindi")
GOLDEN = ROOT / "bench" / "heldout_ml" / "golden_ta_hi.csv"
PHONE_SCRIPT = ROOT / "deploy" / "android" / "device_test.ps1"




class TorchSmsDetector:
    """Minimal stand-in for sentinel.detectors.SmsDetector backed by a PyTorch checkpoint."""

    def __init__(self, model_dir: str, id_map_path: str | None, device: str):
        self.tokenizer = AutoTokenizer.from_pretrained(str(Path(model_dir) / "tokenizer"))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(Path(model_dir) / "sms_model")).to(device).eval()
        self.device = device
        self.lookup = None
        if id_map_path:
            self.lookup = torch.tensor(json.load(open(id_map_path, encoding="utf-8")), dtype=torch.long, device=device)

    @torch.no_grad()
    def probs_batch(self, texts: list[str], batch: int = 128) -> list[tuple[float, float, float]]:
        out: list[tuple[float, float, float]] = []
        for start in range(0, len(texts), batch):
            enc = self.tokenizer(texts[start:start + batch], truncation=True, max_length=128,
                                 padding=True, return_tensors="pt").to(self.device)
            ids = enc["input_ids"]
            if self.lookup is not None:
                ids = self.lookup[ids.clamp(min=0, max=len(self.lookup) - 1)]
            logits = self.model(input_ids=ids, attention_mask=enc["attention_mask"]).logits
            out.extend(tuple(float(v) for v in row) for row in torch.softmax(logits.float(), dim=-1).cpu())
        return out

    def predict(self, text: str) -> dict:
        ham, unwanted, scam = self.probs_batch([text])[0]
        probs = {"ham": ham, "unwanted": unwanted, "scam": scam}
        return {"probs": probs, "label": max(probs, key=probs.get)}


def phone_messages() -> list[tuple[str, str, str]]:
    """(name, text, expected level class) for acceptance line 6."""
    script = PHONE_SCRIPT.read_text(encoding="utf-8")
    pairs = re.findall(r'Label\s*=\s*"([^"]+)"[^}]*?Text\s*=\s*"([^"]+)"', script, flags=re.S)
    wanted = {"SBI KYC": "high", "Hinglish Axis card KYC": "high", "Hinglish UPI refund PIN": "high",
              "Instant loan .apk link": "high", "Order delivered": "low"}
    out = [(label, text, wanted[label]) for label, text in pairs if label in wanted]
    return out


def score_arm(name: str, model_dir: str, id_map: str | None, rows: list[dict], texts: list[str], device: str) -> dict:
    det = TorchSmsDetector(model_dir, id_map, device)
    probs = det.probs_batch(texts)
    arm_rows = [dict(row, p_ham=p[0], p_unwanted=p[1], p_scam=p[2]) for row, p in zip(rows, probs)]
    levels = sim._fuse_levels(arm_rows, sim.shipped_params())
    records = [{"truth": row["truth"], "level": lv["level"]} for row, lv in zip(rows, levels)]
    result: dict = {"model_dir": model_dir, "id_map": id_map, "heldout": {"Overall": sim._metrics(records)}}
    for lang in LANGS:
        result["heldout"][lang] = sim._metrics([rec for row, rec in zip(rows, records) if row["language"] == lang])
    result["heldout_levels"] = [lv["level"] for lv in levels]

    golden = list(csv.DictReader(open(GOLDEN, encoding="utf-8")))
    result["golden"], result["golden_wrong"] = {}, []
    for lang in ("Tamil", "Hindi"):
        correct = total = 0
        for row in (r for r in golden if r["language"] == lang):
            level = analyse(row["text"], sms_det=det)["evidence"]["level"]
            ok = (level in ("medium", "high")) == (row["truth"] == "risky")
            correct += ok
            total += 1
            if not ok:
                result["golden_wrong"].append({"id": row["id"], "truth": row["truth"], "level": level})
        result["golden"][lang] = {"correct": correct, "total": total}
    result["phone"] = []
    for label, text, expected in phone_messages():
        level = analyse(text, sms_det=det)["evidence"]["level"]
        result["phone"].append({"message": label, "level": level, "expected": expected, "ok": level == expected})
    print(f"[{name}] overall {result['heldout']['Overall']['risky_recall']:.3f} / {result['heldout']['Overall']['fpr_ham']:.3f}; "
          f"golden {result['golden']}", flush=True)
    return result


def write_markdown(report: dict, path: Path) -> None:
    arms = list(report["arms"])
    lines = ["# SMS model arms on the held-out and golden sets", "",
             "Shipped fusion rules. Predicted risky = level medium or high. Source json next to this file.", "",
             "| Slice | n | " + " | ".join(f"{a}: recall / false alarms" for a in arms) + " |",
             "|---|---|" + "---|" * len(arms)]
    for slice_name in ("Overall",) + LANGS:
        cells = []
        for arm in arms:
            m = report["arms"][arm]["heldout"][slice_name]
            cells.append(f"{m['risky_recall']:.3f} / {100 * m['fpr_ham']:.1f} %")
        n = report["arms"][arms[0]]["heldout"][slice_name]["n"]
        lines.append(f"| {slice_name} | {n} | " + " | ".join(cells) + " |")
    lines += ["", "| Golden set (hand-written) | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for lang in ("Tamil", "Hindi"):
        lines.append(f"| {lang} correct | " + " | ".join(
            f"{report['arms'][a]['golden'][lang]['correct']} of {report['arms'][a]['golden'][lang]['total']}" for a in arms) + " |")
    lines += ["", "| Phone test message | expected | " + " | ".join(arms) + " |", "|---|---|" + "---|" * len(arms)]
    for index, item in enumerate(report["arms"][arms[0]]["phone"]):
        lines.append(f"| {item['message']} | {item['expected']} | " + " | ".join(
            report["arms"][a]["phone"][index]["level"] for a in arms) + " |")
    lines += ["", "Level changes between arms on English + Hinglish held-out rows: "
              + ", ".join(f"{k}: {v}" for k, v in report["english_hinglish_level_changes"].items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs="+", help="NAME=MODEL_DIR[,ID_MAP_JSON]")
    parser.add_argument("--out", required=True, help="output path without extension")
    args = parser.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    rows, missing = sim._load_rows()
    text_by_hash = {dump_probs.compute_text_hash(r["text"]): r["text"]
                    for r in csv.DictReader(open(sim.HELDOUT_CSV, encoding="utf-8", newline=""))}
    texts = [text_by_hash[row["text_hash"]] for row in rows]
    report: dict = {"rows": len(rows), "missing_joins": missing, "arms": {}}
    for spec in args.arms:
        name, _, rest = spec.partition("=")
        model_dir, _, id_map = rest.partition(",")
        report["arms"][name] = score_arm(name, model_dir, id_map or None, rows, texts, device)

    names = list(report["arms"])
    en_idx = [i for i, row in enumerate(rows) if row["language"] in ("English", "Hinglish")]
    report["english_hinglish_level_changes"] = {
        f"{names[0]} vs {other}": sum(report["arms"][names[0]]["heldout_levels"][i] != report["arms"][other]["heldout_levels"][i]
                                      for i in en_idx) for other in names[1:]}
    shipped = sim._fuse_levels(rows, sim.shipped_params())
    report["agreement_with_device_dump"] = {
        name: sum(a == b["level"] for a, b in zip(report["arms"][name]["heldout_levels"], shipped)) / len(rows) for name in names}
    for name in names:
        del report["arms"][name]["heldout_levels"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, out.with_suffix(".md"))
    print(json.dumps({k: report[k] for k in ("english_hinglish_level_changes", "agreement_with_device_dump")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
