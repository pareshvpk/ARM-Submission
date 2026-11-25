# Round 3: false alarms on real genuine SMS. Pre-registered rule (2026-11-12, before any round-3 number)

Plan: pre-registered in this file. Background and the real-inbox
measurement: `RESULTS.md`. Experiment copy only until the port step.

## Sets

- **S**: 3,012 redacted real messages from registered senders (`bench/heldout_ml/real_sms.csv`, git-ignored),
  split by sender header: hash of the header even = development, odd = test
  (`bench/heldout_ml/real_sms_split.json`). Only the development half is read or trained on. The manager had read
  about 40 rows across both halves before the split; this is recorded as a limit.
- **Genuine senders** in S: DLT header suffix -S, -T or -G. Promotional: -P. Others: unknown.
- **H**: held-out synthetic set (English, Hinglish, Tamil, Hindi slices). **G**: golden set. **R**: 12 RBI
  advisories (development only).
- **M**: owner-labelled messages from mobile-number senders (likely spam or scam only), when available.

## Definitions

- **Alert** = the app posts a notification. Baseline: level medium or high. New policy: level high, or level
  medium with threat evidence (cue of type credential_request, payment_request, threat or app_install after the
  warning-clause filter; or an impersonation cue together with any link; or an untrusted link at or above the
  URL label threshold).
- Scam recall under a policy = share of risky rows that alert.

## Changes under test

1. Alert policy as defined above (cause 1).
2. Warning-clause filter: credential or payment cues inside a negated or warning clause are not counted (cause 3).
3. Model fine-tuned with the development half of S as genuine and promotional rows (cause 2), run later.

Changes 1 and 2 are scored first with the shipped model (no training), then with the fine-tuned models.

## Acceptance (test half of S; baseline = shipped v5, shipped rules)

1. Genuine senders: alert rate at most 5.0 %; HIGH at most 1.0 %.
2. All registered senders: alert rate at most 15.0 %.
3. H English and H Hinglish: scam recall (alerts) at most 1.0 point below baseline; false alarms (alerts on
   ham) not above baseline.
4. H Tamil and H Hindi: scam recall at least 0.90; false alarms at most 5 %.
5. Golden set at least 54 of 60 per language (correct = scam alerts, genuine does not); six phone test messages:
   four scams alert, two genuine do not.
6. M: every owner-confirmed scam alerts (reported always; binding when at least 10 scams are confirmed).

Changes 1 and 2 alone are expected to fail line 1 on HIGH (they do not touch HIGH). They are still reported
line by line, because they are candidates for an early port on their own if line 3 holds and alert rates fall.
A partial port decision is the owner's, made on the table.

One retry, changing one knob stated before the retry: the threat cue list, or the weight of the real rows.
