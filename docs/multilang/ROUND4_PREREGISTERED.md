# Round 4: recalibrate run 3 on validation data (written before any round-4 number was seen)

Date: 2026-11-12. Owner decision: option C (run 3 + alert policy + recalibration).

## Why

Runs 1 to 4 were all scored with `sms_temperature` 3.0, the value fitted for shipped v5. A fine-tuned
model has a different confidence scale, so part of the recall loss measured in round 3 may come from
the scale and not from the model. Organiser guidance (session 2026-11-12, slide 07): select
thresholds on validation data, not on the test set.

## Fixed

- Model: `models/sms_v6ml_run3` (unchanged, no training).
- Alert policy: policy2 (`sentinel/alert_policy.py:should_alert` with the SMS label).
- All fusion weights and both level thresholds (medium 0.4, high 0.7) stay as shipped.

## The one fitted value

`sms_temperature`, chosen from the grid already used by `bench/heldout/calibrate.py`:
0.5, 0.75, 1.0, 1.5, 2.0, 3.0.

## Validation data (the only data used to choose)

- V: the 4,000 template-split validation rows of the training corpus, rebuilt locally with
  `training/sms/finetune_sms.py:build_train_val_split(seed=42, sample_size=120000, val_size=4000)`.
  Run 3 never trained on them.
- D: the development half of the real inbox, genuine senders only (291 messages). Run 3 trained on
  these, so D is optimistic and is used only as a guard, not as evidence.

Not used to choose: the real test half, the held-out set, the golden set, the phone messages.

## Selection rule

Among grid values where the alert rate on V rows labelled ham is at most 1.0 % AND the alert rate
on D is at most 2.0 %, take the value with the highest alert rate on V rows labelled scam.
Tie: the higher temperature. No value qualifies: keep 3.0.

## Scoring (once, after the value is fixed)

Same lines as `ROUND3_PREREGISTERED.md`, on the real test half and the held-out set:
genuine senders alerted at most 5 %, HIGH at most 1 %; all registered senders alerted at most 15 %;
held-out English and Hinglish recall not more than 1.0 point below shipped v5 with the shipped
policy (0.935 and 0.932); English false alarms not above 0.5 %; phone messages 6 of 6.
Reported without a line: Hindi, Tamil, golden set.

## Known weakness, stated in advance

The real test half has already been scored three times (round-3 simulations v2, v3, v4), and the
decision to try recalibration was made after seeing those results. Its numbers in this round are
therefore not blind. The held-out set has also been seen many times. This round can show whether
recalibration helps; it cannot give an unbiased final estimate.

## If it fails

No further fitting. The owner chooses between run 3 at temperature 3.0 (option B) and shipped v5
with the new alert policy (option A), with all tables in hand.
