# DT-2 retraining plan (pre-registered 2026-11-08, before any training run)

Problem: the SMS model (v5, `models/sms_v5d`) scores ordinary Indian retail promotions as scam. The shoe-store
scam weight 0.9) it is MEDIUM / unwanted instead of HIGH / scam, but not LOW. The training corpus already has many
`unwanted` (promotional) rows, so retraining from scratch on the same data is not expected to change this.

## Method

1. Hard-negative mining on the training corpus only (`data/processed/sms/*.parquet`), never on the held-out set
   (`bench/heldout/heldout_20261107.csv`, whose rows were removed from the corpus by hash): run the current v5
   checkpoint, collect `unwanted` and `ham` rows it predicts as `scam`, and keep their counts by source.
2. Fine-tune from the v5 checkpoint for a short run (1 epoch or less) on a mix of the original training data and
   the mined hard negatives (upweighted), same tokenizer, same label set, same max length 128.
   check export parity against the PyTorch logits (same thresholds as `training/sms/export_sms.py`).
   (calibration as shipped), on the same test half and split as `bench/heldout/calib_20261108/calibration.md`.

## Acceptance (fixed now; evaluated on the held-out test half, shipped fusion, versus the shipped v5 + calibration)

- Risky recall (level medium or high) does not drop by more than 1.0 percentage point (baseline 77.26 %).
- Ham false-alarm rate (level medium or high on ham) is not higher than baseline (10.53 %).
- English and Hinglish risky recall each drop by at most 1.0 point (baselines from the calibrated test half).
- The four phone test scams (SBI KYC, Axis KYC, UPI PIN, loan APK) stay HIGH.
- The shoe-store promotion is LOW.

If any criterion fails, the new model is not shipped; the result and the numbers are recorded here.

## Result of step 1 (hard-negative mining), 2026-11-08: retraining stopped before training

`training/sms/mine_hard_negatives.py` scored every ham and unwanted row of `data/processed/sms` (1,108,719 rows,
25.5 min on the RTX 4060; 0 rows overlapped the held-out set) with the v5 checkpoint, which scores the shoe-store
promotion p_scam 0.72 in PyTorch fp32 (0.687 for the shipped int8 `.pte`). It predicted scam on 92,158 rows
(44,935 ham, 47,223 unwanted), concentrated in two non-Indian sources: dharshiyanacc_spam_ham_phishing (41,992;
old email spam with `escapenumber` placeholders, replica and stock spam) and vinit119_sms_scam (28,343; tweets and
promotional links). Samples are in the mining output (`training_runs/mine_full/`, not committed: raw text).

Targeted check: the corpus holds 36,490 promotion-like unwanted rows (promotion words, no link, OTP, PIN, KYC,
password, verify, prize or refund words), 20,523 of them from the Indian kritikgianta_merged_sms source. The model
predicts scam on 4,399 of them (12.1 %), and none of those come from kritikgianta: the model already treats typical
Indian promotions as unwanted. The 4,399 are mostly scams with a loose unwanted label (prize-call scams such as
"Urgent! call ... cash await collection", handset-prize offers, loan bait, replica and pill spam).

Decision: no fine-tune. Training on these hard negatives would teach the model to call prize and loan scams
unwanted, which the acceptance criteria above forbid (risky recall), and the corpus has no clean examples of the
shoe-store kind of error to learn from. The shipped calibration (promotion MEDIUM / unwanted) stays. The way to make
retail promotions LOW is new, correctly labelled real Indian promotional SMS (collected with consent), then this
plan from step 2 with the same criteria.
