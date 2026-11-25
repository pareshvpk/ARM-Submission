# PS3 SMS Threat & Scam Detector Training

Bharat AI-SoC Challenge 2026-27, Problem Statement 3 (On-Device Scam SMS Classifier).

## Kaggle Commands
- Push kernel: `kaggle kernels push -p training/sms`
- Status: `kaggle kernels status <kaggle-user>/ps3-sms-classifier`
- Output fetch: `kaggle kernels output <kaggle-user>/ps3-sms-classifier -p training/sms/output`

## DT-2 Retraining Tooling

Three local tools implement the DT-2 retraining plan (`docs/device_tests/DT-2_retraining_plan.md`).
None of them reads the held-out CSV for training; only mining reads it, to exclude overlaps.

### 1. Hard-negative mining — `training/sms/mine_hard_negatives.py`

```powershell
python -m training.sms.mine_hard_negatives --out-dir tmp_work/hard_negatives --limit 5000
```

Loads the v5 checkpoint (`models/sms_v5d/sms_model`, tokenizer, `id_map.json`),
scores every ham/unwanted row of `data/processed/sms/*.parquet` on CUDA if
available (max length 128, same tokenization as training: fix_mojibake,
`padding="max_length"`, id_map remap), and writes:

- `hard_negatives.parquet`: `text, label, source_file, p_scam` for rows the
  model predicts as scam.
- `summary.json`: rows scanned, hard negatives, **excluded held-out-overlapping
  rows**, counts by source file and label.

Rows whose text hash appears in `bench/heldout/heldout_20261107.csv` (same sha1
hash as `bench/heldout/eval_heldout.py:compute_text_hash`) are excluded before
scoring, so the held-out set is never scored or mined. `--limit` caps scanned
rows for smoke runs.

### 2. Fine-tune — `training/sms/finetune_sms.py`

```powershell
python -m training.sms.finetune_sms --hard-negatives tmp_work/hard_negatives/hard_negatives.parquet --hn-weight 5 --out-dir tmp_work/finetuned_sms
```

Fine-tunes the v5 checkpoint (not from scratch) on a stratified sample of the
original training rows — built the same way `train_sms.py` builds its set
(same source exclusion, conflict/dedup handling, per-source caps, template-hash
80/10/10 split; `fix_mojibake`, `template_key`, `should_exclude_source`,
`map_label` are imported from `train_sms`, not copied) — mixed with the mined
hard negatives upweighted by `--hn-weight` (effective rows = round(n × weight)).
AdamW, lr `--lr` (default 1e-5), 1 epoch by default, CUDA if available, seed 42,
max length 128, no scheduler. Like `train_sms` it saves:

- `sms_model/` (Hugging Face `config.json`, `model.safetensors`), `tokenizer/`,
  `id_map.json` (copy of the base id_map), `parity_inputs.pt` (old-space ids +
  validation logits, for export) and `training_log.json` (rows used, hard-negative
  count/weight, loss per `--log-interval`, validation macro F1 and per-class
  recall on the held-back template-split validation portion of the training
  corpus — never the held-out CSV). `--max-steps` caps steps for smoke runs.

### 3. Export — `training/sms/export_sms.py`

Same ExecuTorch 1.5.1 / torch 2.15.0+cpu route as v5 (fp32 pruned .pte, int8
via the manual-int8-embedding Route B, same parity thresholds):

```powershell
python training/sms/export_sms.py --model-dir tmp_work/finetuned_sms/sms_model --tokenizer-dir tmp_work/finetuned_sms/tokenizer --parity-path tmp_work/finetuned_sms/parity_inputs.pt --out-dir tmp_work/finetuned_sms/exported
```

Defaults are the v5 pipeline (`models/sms_v5/sms_model` → `models/sms_v5d`).
The fine-tuned checkpoint is already pruned (vocab 72,862), so for it export
needs the input id_map: pass `--id-map models/sms_v5d/id_map.json`, or place
`id_map.json` next to the model dir (fine-tune writes one). Without it,
full-vocab models export as before. Exported example inputs are remapped into
pruned space before tracing (same .pte graph; no out-of-bounds embedding
lookup on arbitrary parity ids). Use `--dynamic-seq` for dynamic length
2–128 as in v5d.

## Outputs (`/kaggle/working`)
- `metrics.json`: Comprehensive evaluation metrics (macro F1, per-class P/R/F1, binary risky metrics, confusion matrix, per-source/lang/channel/synthetic metrics, Indian subset metrics, excluded eval metrics, 30 hand-written test messages evaluation, latency).
- `errors.csv`: 200 most confident wrong test predictions with text, true, pred, prob, source, lang.
- `sms_model/`: Hugging Face fine-tuned model (`ai4bharat/indic-bert` or fallback `distilbert-base-multilingual-cased`).
- `tokenizer/`: Tokenizer configuration and weights for on-device app inference.
- `sms_model.pte`: ExecuTorch exported XNNPACK-lowered model (`.pte`) with numerical parity verification against PyTorch.
- `export.json`: Export metadata, version info, sizes, and parity check result.
- `train_log.txt`: Full execution log.

## Data Policy
- **Source Exclusion**: Entries with `preprocessed: true`, channel `email`, or channel `job_post` are excluded from training and the main test set. They are evaluated separately in `excluded_eval` (up to 20,000 rows).
- **Label Mapping**: 3 classes mapped: `0: ham`, `1: unwanted`, `2: scam` (`spam` mapped to `unwanted`).
- **Cleaning & Deduping**: Empty text dropped; deduplication on `text_hash`; cross-source label conflicts (`text_hash` with multiple classes) dropped.
- **Split & Grouping**: 80/10/10 train/val/test split grouped by `template_key` hash to prevent data leakage from templated synthetic messages.
- **Caps & Balancing**: Per-source cap of 100,000 unique rows (synthetic sources capped at 30,000 each). Weighted cross-entropy class balancing with weights clipped to at most 5x.

## Training v3 Updates
## Training v4 Updates

- **Mojibake Repair**: Added `fix_mojibake` (up to 3 passes trying cp1252/latin-1 decoding to utf-8 with character count check on mojibake set) applied to training chunks and excluded eval set.
- **Binary Risky Metrics**: Added `risky_precision`, `risky_recall`, and `risky_f1` binary metrics (risky = class != 0, zero_division=0) in subset evaluation.
- **FINAL_MODE**: Added `FINAL_MODE` module constant (`True` by default to train on holdout sources when shipping model; set `False` for generalization check to keep them held out).

- **Source Fixes**:
  - `sms_hf_cloveai_india_spam`: label 1 remapped to `scam` (was `unwanted`), marked `synthetic: true`, and evidence updated following manual audit showing scam templates (fake Aadhaar/bill/prize links).
  - `sms_vinit119_sms_scam`: marked `skip: true` (spam label is a Twitter spam-account corpus with stripped punctuation rather than SMS; ham rows include translated junk).
  - `sms_msubhansiddiqui_financial_scam`: marked `skip: true` (news headlines and generic phrases rather than SMS; noisy labels).
- **Held-Out Sources Evaluation**:
  - Four sources are isolated into a dedicated `holdout_df` and excluded from `train`, `val`, and `test`: `sms_hf_bolewara_hinglish_scam`, `sms_junioralive_india_spam`, `sms_karanverma_punjab_fraud`, and `sms_hf_karanverma19_indian_scam`.
  - **Cross-Source Leakage Guard**: drops from `train_df`, `val_df`, and `test_df` any row whose `text_hash` or `template_hash` appears in `holdout_df`.
  - Model predictions on `holdout_df` yield `holdout_eval_metrics` in `metrics.json` (with `per_source` breakdowns) and up to 200 misclassifications saved to `holdout_errors.csv`.
- **Dataset Source**:
  - Kernel metadata updated to use dataset `<kaggle-user>/ps3-sms-corpus`.
- **INT8 Pruning & Quantization**:
  - Vocabulary pruning and INT8 quantization are performed afterwards locally with `training/sms/export_sms.py`.

Note: `<kaggle-user>` in the kernel metadata files and commands stands for your own Kaggle username. Replace it locally before `kaggle kernels push`; do not commit the real name.
