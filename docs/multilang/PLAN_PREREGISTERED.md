# Tamil + Hindi model: pre-registered plan (written 2026-11-10, before any data was added or any model trained)

Published to main on 2026-11-15. Same pattern as
`docs/device_tests/DT-2_retraining_plan.md`.

## Problem

The shipped SMS model (v5, `models/sms_v5d`) with the shipped fusion rules (temperature 3.0, scam weight 0.9) is
strong in English and Hinglish and weak in native scripts. A rule-based script gate was simulated on 2026-11-10 and
rejected (`bench/heldout/sim_script_gate_20261110.md`). The remaining route is more native-script data and a
fine-tune.

## Baseline (shipped v5 + shipped fusion, `bench/heldout/sim_script_gate_20261110.json`, `shipped_rules`, V0)

Predicted risky = level medium or high. All rows are from `bench/heldout/heldout_20261107.csv`, which is synthetic
or mixed; labels are the dataset authors'.

| Slice | n | Risky recall | False alarms on ham |
|---|---|---|---|
| English | 1,209 | 0.936 (617 of 659) | 0.5 % (3 of 550) |
| Hinglish | 1,000 | 0.932 (466 of 500) | 0.0 % (0 of 500) |
| Tamil | 454 | 0.945 (172 of 182) | 30.9 % (84 of 272) |
| Hindi | 1,000 | 0.968 (484 of 500) | 12.8 % (64 of 500) |
| Overall | 13,098 | 0.766 | 10.9 % |

## Method

1. Data added for training (Track B): public Tamil and Hindi SMS or scam datasets with a usable licence, mapped in
   `data/source_map.yaml` with explicit label maps and evidence; and machine translation (IndicTrans2) of a
   stratified sample of English and Hinglish training rows into Tamil and Hindi, flagged synthetic. No row whose
   text hash or template hash matches a held-out row or a golden-set row is used.
2. Fine-tune from the v5 checkpoint with `training/sms/finetune_sms.py`, 1 epoch, same tokenizer, label set and
   max length 128, on Kaggle under a new kernel slug.
3. Score with PyTorch fp32 first, shipped fusion unchanged. Export and on-device confirmation only if the rule
   below passes.

## Evaluation sets

- **H**: the Tamil, Hindi, English and Hinglish rows of the held-out set above (synthetic).
- **G**: golden set `bench/heldout_ml/golden_ta_hi.csv`, 60 Tamil + 60 Hindi hand-written messages, half scam and
  half genuine, wording and labels checked by the owner before the first training run. Frozen after that check.
- **R**: the owner's real messages (at most about 50), parsed by `data/tools/parse_whatsapp_export.py`. Reported
  only. Too few to gate on.

## Acceptance rule (fixed now)

The candidate is adopted in the copy only if every line holds, against the baseline above:

1. English: risky recall at least 0.926 (drop at most 1.0 point); false alarms at most 0.5 %.
2. Hinglish: risky recall at least 0.922; false alarms at most 0.0 % (no new false alarm on the 500 ham rows).
3. Tamil (H): false alarms at most 5.0 %; risky recall at least 0.90.
4. Hindi (H): false alarms at most 5.0 %; risky recall at least 0.90.
5. Golden set (G): at least 54 of 60 correct in Tamil and at least 54 of 60 correct in Hindi. Correct means a scam
   is medium or high and a genuine message is low.
6. The four phone test scams (SBI KYC, Axis KYC, UPI PIN refund, loan APK) stay HIGH; "Your order has been
   delivered" and the HDFC OTP message stay LOW.

The baseline v5 is also scored on G before training, so the report shows the change.

If any line fails: the candidate is not adopted and the numbers are recorded. One second run is allowed, changing
only the weight or count of translated rows. After that the experiment stops and is written up.

## Addendum 2026-11-11: vocabulary pruning arm (written before this arm was scored)

Measured on 2026-11-11 (`data/tools/measure_vocab_pruning.py`, `docs/multilang/vocab_pruning_20261111.json`): the
shipped model keeps 72,862 of 250,002 tokens (only tokens seen in the training corpus). Text tokens outside that
set reach the model as the unknown token. Share of real (non-padding) tokens mapped to unknown: golden Tamil
41.6 %, held-out Tamil 33.2 %, Kannada 66.8 %, Gujarati 77.3 %, Kashmiri 75.4 %, Odia 60.2 %, Malayalam 55.3 %,
Punjabi 47.5 %, Assamese 18.8 %, Telugu 12.1 %, Marathi 5.8 %, Hindi 1.7 % (golden Hindi 0.9 %), Bengali 0.3 %,
English and Hinglish 0.0 %.

So part of the native-script weakness may be the export step, not the trained model. New arm, no training:

- **Arm U (unpruned v5):** the same v5 weights before pruning (`models/sms_v5/sms_model`, 250,037-token
  embedding, PyTorch fp32), scored on H and G with the shipped fusion, next to **Arm P (pruned v5)**: the same
  PyTorch weights with the shipped `id_map.json` applied to the input ids, which is what the device computes
  apart from int8 rounding.
- Both arms are judged by the acceptance rule above, unchanged.
- English and Hinglish must be identical between U and P up to rounding, because no English token is pruned. If
  they differ by more than 2 rows in level, the scoring script is wrong and the arm is void.
- If Arm U passes or clearly improves Tamil without any training, the cheapest fix is to keep Tamil and
  Devanagari script tokens when pruning. That fix would be a candidate for the original project, because it
  changes the export and not the trained weights. It would still need export parity and an on-device check.
- Whatever Arm U shows, fine-tuning for this experiment starts from the unpruned checkpoint, since a pruned
  embedding cannot learn tokens it does not contain.

Limits known before scoring: G rows have no on-device URL-model output, so both arms use the pipeline's URL
indicator fallback for G; H rows reuse the recorded cue and URL columns of the 2026-11-08 dump.

## Deviation recorded 2026-11-11, before the first training run

The plan said training would not start until the owner had checked the golden set. The owner then asked for the
work to be finished without waiting. Training therefore starts with the golden set as drafted on 2026-11-10,
frozen at SHA-256 `4c73c99b8ab628b4df6f1f73d645fee16bb4b1ae97c4720d2086fa7b1ba52f11`
(`bench/heldout_ml/golden_ta_hi.csv`). It was written before any training and before any model was scored on it.
If the owner later corrects rows, results are reported on both the frozen and the corrected file.

Result of the vocabulary arm (scored after the addendum above was written): see
`docs/multilang/FINDINGS_20261111.md`. Arm U fails lines 3 and 4. Because both v5 arms already clear line 5, the
golden set cannot show an improvement on its own.

## Known weaknesses of this design (stated in advance)

- H is synthetic and may itself be translated or templated text. Training on machine-translated rows can raise
  scores on H without helping real messages. G and R exist to expose that; a pass on H with a fail on G is a fail.
- G is written by the same people who run the experiment. It is small and not a sample of real traffic.
- A pass means "good enough to test with real users", not "Tamil and Hindi are solved".
