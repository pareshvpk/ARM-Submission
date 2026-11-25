# Held-out evaluation (2026-11-07)

Decontaminated Indian SMS test set for research items P3/P12. Rows whose text hash already appears in the training corpus (`data/processed/sms/*.parquet`, `text_hash` column) are removed. Exact duplicate texts inside the output are removed. `truth` is `ham` or `risky` (`spam` and `scam` map to `risky`).

## Sources

- carnageiron/scam-ham-india (2272 rows, columns `text,label`; `ham`/`spam`) — https://huggingface.co/datasets/carnageiron/scam-ham-india — Apache-2.0. README: mix of real Indian SMS and synthetic examples; `spam` includes carrier promotions.
- anmolshrivastav/scam_ham_india_14_languages (14000 rows, columns `text,label,language`; `ham`/`scam`; 14 languages, 1000 per language) — https://huggingface.co/datasets/anmolshrivastav/scam_ham_india_14_languages — MIT. Tagged synthetic by its author; synthetic.

## Synthetic caveats

carnageiron is a mix of real and synthetic (synthetic are cleaner/more grammatical; English only). anmolshrivastav is synthetic (tagged synthetic) across 14 languages. `synthetic` in `heldout_20261107.csv` is `mixed` for carnageiron and `true` for anmolshrivastav.

## Run

Build (reads `data/raw/ext/heldout_20261107/`, writes `heldout_20261107.csv` and `heldout_20261107_build.json`):

```
.venv\Scripts\python.exe bench/heldout/make_heldout.py
```

Evaluate on Linux (no Llama, same path as `python -m sentinel scan --no-llm`; `--models-dir` defaults like the CLI):

```
python bench/heldout/eval_heldout.py bench/heldout/heldout_20261107.csv --models-dir ~/ps3/models --out-json bench/heldout/eval_report.json --out-csv bench/heldout/eval_predictions.csv
```

Predictions CSV has hash only, never message text (`text_hash,source,language,truth,pred_label,pred_level,risk`). Predicted risky is `medium`/`high` (same as `AlertPolicy.isThreat`).
