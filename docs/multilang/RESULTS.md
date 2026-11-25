# Tamil + Hindi experiment: result (2026-11-11)

Published to main on 2026-11-15. Rule and method: `PLAN_PREREGISTERED.md`. Findings before
training: `FINDINGS_20261111.md`. Numbers: `arms_run2_20261111.json` (all three models scored in one run).

## Verdict

**Not adopted.** Both allowed runs fail line 1 of the pre-registered rule (English false alarms must not rise).
Run 2 fails it by one message. Every other line passes in both runs. Per the plan the experiment stops here; a
third run would need a new rule written in advance.

The result is still a strong lead: Tamil and Hindi false alarms on the synthetic held-out set fall from 31.2 % and
12.8 % to 0.0 % and 1.2 to 2.4 %, with English and Hinglish recall slightly up.

## Numbers (PyTorch fp32, shipped fusion rules, risky = level medium or high)

| Held-out slice | n | Shipped v5 (pruned) | Run 1 (added rows weight 1.0) | Run 2 (weight 0.5) | Rule |
|---|---|---|---|---|---|
| English recall / false alarms | 1,209 | 0.935 / 0.5 % (3 of 550) | 0.958 / 1.5 % (8) | 0.959 / 0.7 % (4) | >= 0.926 / not above baseline |
| Hinglish | 1,000 | 0.932 / 0.0 % | 0.942 / 0.0 % | 0.924 / 0.0 % | >= 0.922 / 0 new |
| Tamil | 454 | 0.940 / 31.2 % | 1.000 / 0.0 % | 1.000 / 0.0 % | >= 0.90 / <= 5 % |
| Hindi | 1,000 | 0.964 / 12.8 % | 0.944 / 1.2 % | 0.962 / 2.4 % | >= 0.90 / <= 5 % |
| Overall (14 languages) | 13,098 | 0.765 / 11.1 % | 0.883 / 16.1 % | 0.890 / 19.6 % | not in the rule |
| Golden Tamil / Hindi correct of 60 | | 56 / 58 | 59 / 59 | 59 / 57 | >= 54 each |
| Six phone test messages | | all right | all right | all right | all right |

| Rule line | Run 1 | Run 2 |
|---|---|---|
| 1 English | FAIL (false alarms 8 against 3) | FAIL (4 against 3) |
| 2 Hinglish | pass | pass |
| 3 Tamil | pass | pass |
| 4 Hindi | pass | pass |
| 5 Golden | pass | pass |
| 6 Phone messages | pass | pass |

## Training runs

Kaggle kernel `ps3-sms-multilang-exp` (private), fine-tune from the unpruned v5 checkpoint, 1 epoch, lr 1e-5,
batch 64, with `training/sms/finetune_sms.py --id-map identity --extra-rows`.

| | Run 1 (kernel v1) | Run 2 (kernel v2) |
|---|---|---|
| Original corpus sample | 60,000 | 60,000 |
| Added rows used (of 66,265) | 66,265 | 33,133 (weight 0.5) |
| Steps / validation macro F1 | 1,973 / 0.983 | 1,456 / 0.981 |
| Model folder | `models/sms_v6ml_run1` | `models/sms_v6ml_run2` |

Added rows: Tamil machine-translated 25,263; Hindi machine-translated 25,111; Hindi public sets 15,891
(`docs/multilang/dataset_survey.md`). Zero text-hash or template-hash overlap with the held-out and golden sets
(`data/processed_ml/ml_leak_removal.json`).

## What the English failure is (read, run 1)

`bench/heldout_ml/show_arm_errors.py`: run 1 is wrong where shipped v5 is right on 7 English rows and right where
v5 is wrong on 17. Six of the seven are one template, "Flight reminder: Your flight to <city> departs tomorrow at
<time>. Web check-in is now open.", scored just over the medium threshold (risk 0.41 to 0.48 against 0.40). Run 2
was not read row by row.

## Limits of this evidence

- The held-out set is synthetic and templated, and the Tamil and Hindi training rows are machine-translated or
  synthetic too. Tamil at 454 of 454 is too clean to trust; resemblance between two synthetic sources can produce
  it. Only real Tamil and Hindi messages can confirm the gain. The owner's real messages (set R) have not been
  provided yet.
- The golden set was not checked by the owner (frozen by hash, see the deviation note in the plan) and is too easy
  to discriminate: shipped v5 already scores 56 and 58 of 60.
- Other scripts get worse, not better: overall false alarms rise from 11.1 % to 16 to 20 %, because the unpruned
  model sees scripts the shipped vocabulary hides and was not given genuine text in them. A shippable version would
  have to prune again and keep only Latin, Tamil and Devanagari tokens, and that export was not built or measured.
- These are PyTorch numbers on a PC. No int8 export, no parity check and no on-device run was done, because the
  rule was not passed.
- Machine-translation flaws seen in a 36-row read: acronyms spelled with dots (SBI as "எஸ். பி. ஐ."), one brand
  translated as a word, some non-Indian or garbled source rows.

## Real messages (set R), scored 2026-11-11 after the verdict above

The owner supplied a WhatsApp export of the Reserve Bank of India chat and a text file of advisories.
`data/tools/parse_whatsapp_export.py` kept 12 messages (6 Tamil, 3 Hindi, 3 English), all official advisories, all
labelled genuine. The file is git-ignored. Scores: `real_R_20261111.md/.json` (ids and levels only, no text).

| | Shipped v5 | Run 1 | Run 2 |
|---|---|---|---|
| Genuine messages left at low risk, of 12 | 1 | 1 | 0 |
| Tamil, of 6 | 0 | 1 | 0 |
| Hindi, of 3 | 1 | 0 | 0 |
| English, of 3 | 0 | 0 | 0 |

- **The fine-tune did not help on real messages.** Eleven or twelve of twelve official advisories are flagged by
  every model. The synthetic gains in the tables above did not carry over to this kind of message.
- Eleven are flagged at medium with label `unwanted`. One English advisory (re-KYC, "update your KYC today") is
  **HIGH, scam, 0.72 in all three models, including the shipped one**: the rule for urgency together with a
  credential mention fires, although the message warns against fraud and links only to `rbi.org.in`.
- So this is a pipeline issue as much as a model issue, and it exists in English in the shipped product.

Limits: one sender, one genre (long WhatsApp broadcasts of 460 to 1,060 characters with emoji and bullet lists,
not SMS; the model reads only the first 128 tokens), twelve messages. It says nothing about ordinary Tamil or Hindi
SMS. It does show that official warnings which quote scam wording are treated as threats.

## Real SMS inbox (set S), read from the owner's phone on 2026-11-11/12 with consent

`data/tools/pull_sms_redacted.py` read 6,356 inbox messages over adb (read-only, nothing written to the phone),
skipped 390 from plain mobile numbers (personal), removed 2,954 repeats of the same template, and kept 3,012
messages from registered business senders: 2,696 Latin script (English and Hinglish), 313 Tamil, 2 Hindi, 1
Malayalam, dated 2021 to 2026. Redaction is done in memory; only redacted text is stored, in git-ignored files.
Scores: `bench/heldout_ml/score_sms_levels.py` -> `docs/multilang/sms_levels_summary.json` (counts only).

Sender class comes from the DLT header suffix where present: -S, -T, -G = genuine (521 messages), -P =
promotional (109), no suffix = unknown (2,382). Registered senders are almost never scams, so HIGH on any of these,
and MEDIUM on a genuine one, is a false alarm.

| Slice | n | Shipped v5: medium / high | Run 1: medium / high | Run 2: medium / high |
|---|---|---|---|---|
| Genuine senders, all | 521 | 12.3 % / 9.6 % | 18.0 % / 2.7 % | 17.7 % / 2.3 % |
| Genuine, English or Hinglish | 438 | 10.7 % / 5.3 % | 16.0 % / 3.2 % | 15.8 % / 2.7 % |
| Genuine, Tamil | 81 | 21.0 % / 33.3 % | 29.6 % / 0.0 % | 28.4 % / 0.0 % |
| Promotional senders | 109 | 32.1 % / 6.4 % | 37.6 % / 6.4 % | 62.4 % / 6.4 % |
| All Tamil | 313 | 31.9 % / 24.9 % | 32.6 % / 1.3 % | 32.9 % / 1.0 % |
| All messages | 3,012 | 38.7 % / 11.4 % | 46.0 % / 6.7 % | 51.1 % / 7.1 % |

Reading:
- **The shipped model flags about 22 % of distinct genuine service and government messages in a real inbox, 9.6 %
  of them as HIGH.** The project's reported false-alarm figures (0.87 % on the test split, 5.1 % on the
  Indian-real subset) do not describe this inbox. In Tamil a third of genuine messages are HIGH.
- **The fine-tune helps on real messages where it counts most:** HIGH false alarms on genuine senders fall from
  9.6 % to 2.3-2.7 %, and in Tamil from 33.3 % to 0.0 %. This is the first evidence on real text that the
  experiment's gain is not only an artefact of synthetic data.
- **It does not reduce the total number flagged:** most of the removed HIGH cases become MEDIUM, and some
  previously low messages become MEDIUM, so genuine messages flagged at any level stay near 20 %.
- What shipped v5 marks HIGH among genuine senders (50 messages; a sample was read): Tamil Jio data-usage alerts
  (22, model-only, no rule fired), Department of Telecom / Sanchar Saathi / TRAI / MyGov advisories with app links,
  mutual-fund statement messages with short links ("Click ... to view the Account Statement"), one RBI SMS.

Corrections and limits:
- A first scoring of this set was wrong and is withdrawn: the redaction replaced ordinary words that had once
  followed "Dear" or "Hi" ("your", "for", "at") with a placeholder, and randomised calendar years. The numbers
  above are from the corrected redaction. The withdrawn figures were higher (shipped genuine 16.1 % / 13.2 %).
- Counts are per distinct template, not per message received. Frequent messages such as OTPs count once, so the
  rate a user experiences is probably lower.
- No URL model was used (PyTorch scoring on the PC uses the pipeline's URL-indicator fallback), and the models
  are fp32, not the on-device int8 export. Link-driven verdicts may differ on the device.
- One phone, one user, mostly one state. Sender class is known for only 630 of 3,012 messages.
- About 40 messages were read by the manager during this analysis. From here the set is split by sender header
  into a development half and a test half (hash of the header, even or odd); only the development half is read.

## If the owner wants to continue (each needs its own rule written first)

1. Real data first: the owner's Tamil and Hindi messages as set R, and the RBI WhatsApp export.
2. Address the single failing template by data, not by threshold: add English transactional reminders (travel,
   bookings) to the training sample, then one new run.
3. Build the export with a Latin + Tamil + Devanagari vocabulary and measure size, parity and the other scripts.
4. Nothing from this experiment should be ported to the original project before 23 November 2026.

## Round 3, run 3 (2026-11-12): NOT PASSED

Source: `docs/multilang/round3_sim_v3.md` / `.json`. Run 3 = unpruned v5 + 120,000 original rows + Tamil and Hindi rows at weight 0.5 + development-half real messages repeated x10. Scored on the untouched test half (1,596 messages, 230 from genuine senders), variant policy2.

| Line of the round-3 rule | Limit | Shipped v5, alert on medium | Run 3 + policy2 | Verdict |
|---|---|---|---|---|
| Genuine senders alerted | at most 5 % | 30.0 % | 1.7 % | pass |
| Genuine senders HIGH | at most 1 % | 13.5 % | 1.7 % (4 of 230) | fail |
| All registered senders alerted | at most 15 % | 54.7 % | 8.3 % | pass |
| Held-out English recall | drop at most 1.0 point | 0.935 | 0.900 | fail (-3.5) |
| Held-out Hinglish recall | drop at most 1.0 point | 0.932 | 0.854 | fail (-7.8) |
| Held-out English false alarms | not above baseline 0.5 % | 0.5 % | 0.2 % | pass |
| Phone test messages | 6 of 6 | 6 of 6 | 6 of 6 | pass |

Other measured values for run 3 + policy2: Tamil 1.000 / 0.4 %, Hindi 0.890 / 1.4 %, golden 58 / 59, genuine Tamil senders 0.0 % alerted.
Reading: the real rows remove almost all false alarms on genuine senders but cost scam recall. Run 2 (no real rows) + policy2 had English 0.958 and Hinglish 0.906 with 11.3 % genuine alerts, so the Hinglish line was already missed before real rows were added; part of the loss comes from the policy, not the model.
Retry (the one allowed, one knob): real-row repeat x10 to x3. Everything else unchanged.

## Round 3, retry run 4 (2026-11-12): NOT PASSED, model arm of round 3 closed

Source: `docs/multilang/round3_sim_v4.md` / `.json`. Run 4 = run 3 with the one knob changed: real rows repeated x3 instead of x10 (training log: 155,257 rows, `real_dev_x3.parquet`). Test half, variant policy2.

| Line | Limit | Shipped v5, alert on medium | Run 3 | Run 4 | Run 4 verdict |
|---|---|---|---|---|---|
| Genuine senders alerted | at most 5 % | 30.0 % | 1.7 % | 3.0 % | pass |
| Genuine senders HIGH | at most 1 % | 13.5 % | 1.7 % | 1.3 % (3 of 230) | fail |
| All registered senders alerted | at most 15 % | 54.7 % | 8.3 % | 6.2 % | pass |
| Held-out English recall | drop at most 1.0 point | 0.935 | 0.900 | 0.873 | fail (-6.2) |
| Held-out Hinglish recall | drop at most 1.0 point | 0.932 | 0.854 | 0.826 | fail (-10.6) |
| Held-out Hindi recall (reported) | none | 0.964 | 0.890 | 0.788 | |
| Held-out Tamil recall (reported) | none | 0.940 | 1.000 | 0.978 | |
| Phone test messages | 6 of 6 | 6 of 6 | 6 of 6 | 6 of 6 | pass |

Reading: fewer real rows gave lower recall, not higher, so recall does not follow the real-row weight in the expected direction. With one seed per setting, differences of 3 to 10 recall points between runs 3 and 4 cannot be told apart from run-to-run variation. No further retry is allowed by the rule. Neither model is adopted under the round-3 rule. All four fine-tuned models were scored with the temperature and thresholds fitted for shipped v5; none was recalibrated.

## Round 4 (2026-11-12): recalibration changes nothing

Source: `docs/multilang/round4_calibration.json`, rule in `ROUND4_PREREGISTERED.md`. Run 3, policy2, validation data only (4,000 template-split validation rows and 291 development-half genuine messages).

Every grid temperature from 1.0 to 3.0 qualifies and gives the same scam alert rate on validation, 98.16 %, with ham alerts 0.63 to 0.67 % and development genuine alerts 0.34 %. Tie rule: 3.0 is kept, so the scores of round 3 stand unchanged and no new scoring pass was run.

Reading: under policy2 a medium verdict alerts when the model's top class is scam, and the top class does not depend on temperature. The recall lost on the held-out set is therefore a change in which class the model picks, not a confidence-scale effect. Validation recall (98.2 %) is far above held-out recall (0.900 English, 0.854 Hinglish), so the loss sits in messages unlike the training corpus. Option C equals option B.

## Export and phone state (2026-11-12, owner chose option C which equals B: run 3 + alert policy)

- Export of run 3 in WSL (`~/sentinel-export`, Python 3.12, torch 2.15.0+cpu, ExecuTorch 1.5.1, torchao 0.18.0): `models/sms_v6ml_run3_export/`, log `models/export_run3.log`, corpus folder built by `data/tools/build_export_corpus.py` (original corpus, added Tamil and Hindi rows, real development rows, all 10,354 Tamil and Devanagari tokenizer pieces).
- Kept vocabulary 79,017 (shipped 72,862). fp32 198.5 MB, max logit difference 5.7e-6, 200 of 200 same class. int8 51.0 MB (shipped 48.7 MB), max logit difference 0.17 (shipped 0.06), 200 of 200 same class, route torchao_linear_plus_manual_int8_embedding.
- Pruned PyTorch model against the full run 3 (`round3_sim_pruned.md`): identical on every reported figure (real test half, held-out English, Hinglish, Tamil, Hindi, golden, phone messages).
- Galaxy M31: run-3 files pushed and checksum-verified, app loads `sms_fp32.pte` (phone has no dot product). Not yet measured on the phone: verdicts for Tamil and Hindi messages, latency of the new model.

## Second inbox, set F (2026-11-12): fresh check of run 3 + alert policy

Source: `docs/multilang/real_sms_f14_score.json` (git-ignored pattern `real_*`), script `bench/heldout_ml/score_second_inbox.py`. Owner's second phone (Galaxy F14), read with consent, redacted with `pull_sms_redacted.py --out real_sms_f14.csv`: 773 inbox messages, 31 from plain mobile numbers skipped, 361 duplicate templates dropped, 381 kept (348 Latin, 32 Tamil, 1 Hindi; 120 from genuine-suffix senders). Never used for training, thresholds or any decision. Scored once.

| Slice | n | Shipped v5, alert on medium | Run 3 + policy2 | Run 3 HIGH |
|---|---|---|---|---|
| All registered senders | 381 | 120 (31.5 %) | 47 (12.3 %) | 7 (1.8 %) |
| Genuine senders | 120 | 42 (35.0 %) | 8 (6.7 %) | 2 (1.7 %) |
| Genuine, template not in first inbox | 108 | 39 (36.1 %) | 7 (6.5 %) | 1 (0.9 %) |
| Sender not in the fine-tune data, template not in first inbox | 208 | 71 (34.1 %) | 35 (16.8 %) | 3 (1.4 %) |
| Genuine Tamil | 10 | 7 | 1 | 0 |
| Tamil, unsuffixed senders | 22 | 8 | 0 | 0 |

Against the round-3 limits: all senders 12.3 % (limit 15 %) holds; genuine senders 6.7 % (limit 5 %) and HIGH 1.7 % (limit 1 %) do not. The improvement over the shipped behaviour repeats on fresh data (35.0 % to 6.7 % on genuine senders), but the level is worse than on the first inbox's test half (1.7 %), which shared senders and an owner with the training rows. Limits: one owner, two phones, 120 genuine messages; no scams in this set, so it says nothing about recall.

## Code-mixed Tamil and Hindi set, owner-checked (2026-11-15)

Source: `bench/heldout_ml/code_mixed_ta_hi_1220.csv`, supplied and checked by the owner (file name says 1200, it holds 1,220 rows). 610 Tamil and 610 Hindi messages in native script mixed with English words; 620 risky, 600 ham; 122 templates with 10 variants each; origin `synthetic_code_mixed`. No text overlaps the 120-message golden set. Aggregate: `bench/results/code_mixed_ta_hi_1220_20261115.json`.

Method: `bench/heldout_ml/code_mixed_dump.py` runs the shipped ExecuTorch models (`sms_v6ml` int8 and `url_v2`) once in WSL; `code_mixed_replay.py` then applies the shipped fusion and alert policy (arm-ps3 code of 2026-11-15). Messages carry no sender, so each is scored as an unknown sender and the registered-sender rule never applies. A message counts as caught when the policy would post a notification.

| Slice | Risky caught | Recall | Ham alerted | False-alarm rate |
|---|---|---|---|---|
| All | 568 of 620 | 91.6 % | 31 of 600 | 5.2 % |
| Tamil | 287 of 310 | 92.6 % | 26 of 300 | 8.7 % |
| Hindi | 281 of 310 | 90.6 % | 5 of 300 | 1.7 % |

Errors sit in 15 of the 122 templates; 3 templates are wrong in all 10 variants.

- Missed scams, model says ham: the "pay Rs 1 to receive a refund" UPI template (10 of 10 in both languages), digital arrest by a caller claiming to be CBI (8 of 20 Tamil, 7 of 20 Hindi), job registration fee (1 Tamil, 3 Hindi), one Hindi OTP request by a "bank manager", one Tamil electricity payment to a WhatsApp number.
- Missed scams, model says unwanted (medium, no notification): "daily 10 % guaranteed profit" investment group (3 of 10 Tamil, 8 of 10 Hindi).
- False alarms: Tamil re-KYC notice telling the customer to visit the branch, no link (10 of 10), Tamil ration issue notice (9 of 10), Tamil voter-list camp (5 of 10), power shutdown notice (2 of 20 Tamil, 5 of 20 Hindi).

Limits: the set is synthetic and templated, so the figures describe 122 message patterns, not 1,220 independent messages. It was not used for any tuning. Not run on a phone. Real Tamil and Hindi inbox behaviour is covered only by the small real slices above.

### Same set on the Galaxy M31 (2026-11-15)

Run on the phone through the debug-build batch mode (`DebugSmsReceiver`, extra `file`): each message goes through the phone's own models, fusion and alert policy with no sender; nothing is stored and no notification is posted. The M31 has no dot-product support, so it runs `sms_fp32.pte`; the PC figures above use `sms_int8.pte`. Files: `bench/results/code_mixed_ta_hi_1220_m31_20261115.json` and `.log` (verdict lines only, no text), comparison script `bench/heldout_ml/code_mixed_cmp_phone.py`.

| Slice | Risky caught | Recall | Ham alerted | False-alarm rate |
|---|---|---|---|---|
| All | 571 of 620 | 92.1 % | 29 of 600 | 4.8 % |
| Tamil | 288 of 310 | 92.9 % | 24 of 300 | 8.0 % |
| Hindi | 283 of 310 | 91.3 % | 5 of 300 | 1.7 % |

Against the PC run: the alert decision differs on 5 of 1,220 messages (all with risk near a threshold), the level on 6, the model's top class on 9; median risk difference 0.0007, largest 0.098. The differences come from fp32 against int8 weights. All 1,220 messages took 3 min 48 s on the phone (about 0.19 s each, detection only, no Llama). A first attempt lost the USB link after 1,159 messages and was discarded; the figures are from the complete second run.

### Same set on the Galaxy F14 (2026-11-15)

Same batch method as on the M31. The F14 (SM-E146B, Android 15, dot-product support) runs `sms_int8.pte`, the same file as the PC run. Files: `bench/results/code_mixed_ta_hi_1220_f14_20261115.json` and `.log`.

| Slice | Risky caught | Recall | Ham alerted | False-alarm rate |
|---|---|---|---|---|
| All | 568 of 620 | 91.6 % | 31 of 600 | 5.2 % |
| Tamil | 287 of 310 | 92.6 % | 26 of 300 | 8.7 % |
| Hindi | 281 of 310 | 90.6 % | 5 of 300 | 1.7 % |

Against the PC run: the alert decision is identical on all 1,220 messages; the level differs on 2 and the model's top class on 1; largest risk difference 0.023. Against the M31 (fp32 model): the alert decision differs on 5 messages. All 1,220 messages took 36 s on the F14 (about 0.03 s each, detection only), against 3 min 48 s on the M31.

### Same set on the moto g73 5G (2026-11-15)

Fresh install (app was not on the phone), 8 model files pushed and accepted by the app's SHA-256 check. moto g73 5G, Android 14, MediaTek Dimensity 930, dot-product support, runs `sms_int8.pte`. Files: `bench/results/code_mixed_ta_hi_1220_g73_20261115.json` and `.log`.

Result: 568 of 620 risky caught (91.6 %), 31 of 600 ham alerted (5.2 %); Tamil 92.6 % / 8.7 %, Hindi 90.6 % / 1.7 %. The alert decision is identical to the PC run and to the F14 on all 1,220 messages. All 1,220 messages took 26 s (about 0.02 s each, detection only).

| Phone | SMS model file | Recall | False alarms | Alert decisions differing from PC | Time for 1,220 |
|---|---|---|---|---|---|
| Galaxy M31 (no dot product) | fp32 | 92.1 % | 4.8 % | 5 | 228 s |
| Galaxy F14 | int8 | 91.6 % | 5.2 % | 0 | 36 s |
| moto g73 5G | int8 | 91.6 % | 5.2 % | 0 | 26 s |

### After the scam-script rules (2026-11-15, evening)

Three known scam scripts were added to the shared rules (digital arrest threat, small payment to release a refund, guaranteed-profit group); details and the full table are in `docs/benchmarks.md`, section "Known scam scripts and the cold-start retry". They were written after seeing the failing templates of this set, so this set no longer tests them independently. The set was split by template number: odd numbers were used to write the rules, even numbers were held back (`bench/heldout_ml/code_mixed_split_replay.py`).

| Slice | Risky caught before | Risky caught after | Genuine alerted (unchanged) |
|---|---|---|---|
| All | 568 of 620 (91.6 %) | 614 of 620 (99.0 %) | 31 of 600 (5.2 %) |
| Tamil | 287 of 310 | 308 of 310 (99.4 %) | 26 of 300 (8.7 %) |
| Hindi | 281 of 310 | 306 of 310 (98.7 %) | 5 of 300 (1.7 %) |
| Odd templates (rules written on these) | 272 of 320 | 318 of 320 | 22 of 300 |
| Even templates (held back) | 296 of 300 | 296 of 300 | 9 of 300 |

