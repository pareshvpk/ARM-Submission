# Tamil + Hindi experiment, round 2: pre-registered plan (written 2026-11-11, before any round-2 data or run)

Round 1 result: `RESULTS.md` (not adopted; both runs failed the English false-alarm line, run 2 by one message).
The owner asked on 2026-11-11 to finish the multi-language work. This is a new round with its own rule.

## What round 1 left open

1. English false alarms rose (3 of 550 to 8, then 4). Read in run 1: one template, a flight reminder.
2. Every evaluation set is synthetic. No real Tamil or Hindi message has been scored.
3. Machine-translated rows spell acronyms with dots and translate some brand names.
4. The fine-tuned model has no on-device form: no pruned vocabulary, no int8 export, no parity or phone run.
5. Scripts other than Latin, Tamil and Devanagari get noisier with the full vocabulary.
6. The golden set is unchecked by the owner and too easy to discriminate.
7. Tamil and Hindi app text (Track D) is drafted but not reviewed or wired in.

## Changes in round 2 (all fixed here, before any is built)

- **A. More of the original corpus in the mix:** the stratified sample of the shipped training corpus goes from
  60,000 to 120,000 rows, so English and Hinglish are not diluted.
- **B. Written transactional ham:** a generator produces genuine transactional messages from templates in English,
  Tamil and Hindi: bank credit and debit, card statement, EMI debit, bill due and bill paid, recharge, gas booking,
  courier and delivery OTP, travel and appointment reminders, salary credit. Varied banks, amounts, dates and
  reference numbers. About 4,000 rows per language, all labelled ham, flagged synthetic.
- **C. Translation clean-up:** dotted acronyms in the existing machine-translated rows are restored to Latin
  letters (SBI, UPI, KYC, OTP, PIN, ATM, EMI, PAN and bank names) by a deterministic rule; no re-translation.
- **D. Added-row weight 1.0** (all cleaned Tamil and Hindi rows once). One run. One retry allowed, changing only
  the size of B.
- **E. Export, only if the rule passes:** vocabulary pruned to tokens seen in the training data plus every
  tokenizer token made only of Tamil or Devanagari characters; int8 and fp32 `.pte`; parity as in
  `training/sms/export_sms.py`; phone run with `deploy/android/device_test.ps1`.

## Honesty about the test set

Change B is a response to what was read in the round-1 errors, including an English template that is in the
held-out set. The held-out English numbers are therefore no longer blind for transactional reminders. To keep one
clean check:

- The generator must not copy any held-out wording. Templates are written from the category list above, not from
  held-out rows, and generated rows whose text hash or template hash matches a held-out or golden row are removed.
- A new small English check set **E2** is written before the run and frozen: 60 genuine English transactional and
  reminder messages and 20 English scams, none copied from the corpus or held-out set.
- The real set **R** (owner's messages, and the RBI WhatsApp export) is scored and reported whenever it arrives.
  Nothing is ported to the original project without R.

## Acceptance rule (fixed now; shipped fusion; baseline = shipped v5 as scored in `arms_run2_20261111.json`)

1. English held-out: risky recall at least 0.925; false alarms at most 3 of 550.
2. Hinglish held-out: risky recall at least 0.922; no false alarm.
3. Tamil held-out: recall at least 0.90; false alarms at most 5 %.
4. Hindi held-out: recall at least 0.90; false alarms at most 5 %.
5. E2: at most 3 of the 60 genuine messages flagged; at least 17 of the 20 scams flagged.
6. Golden set: at least 54 of 60 per language. Six phone test messages as before.
7. After export (step E): int8 agrees with fp32 on the label for at least 99 % of 200 parity inputs; lines 1 to 6
   re-scored through the pruned vocabulary change by at most 1 row per line; `.pte` at most 60 MB.

Fail on any of 1 to 6: not adopted, numbers recorded, at most one retry as stated. Lines 1 to 6 pass but 7 fails:
recorded as "model passes, export does not".

## Amendment 2026-11-11, after set R was scored and before anything in round 2 was built

Set R arrived (12 official RBI advisories) and every model, including shipped v5, flags 11 or 12 of them
(`RESULTS.md`, section Real messages). Round 2 is amended; nothing above had been built yet.

- **F. Advisory ham:** the generator of change B also writes official-advisory style genuine messages in English,
  Tamil and Hindi (fraud warnings that mention KYC, OTP, PIN, digital arrest, money mules; service information
  such as nomination, unclaimed deposits, complaint steps), including long multi-line ones. About 1,500 per
  language. Written from the topic list, not copied from R.
- **G. Pipeline check, measured separately from the model:** the English advisory is HIGH through the
  urgency-plus-credential rule. Round 2 measures, without shipping it, how many held-out, golden, E2 and R rows
  change level if a credential cue is ignored when it sits in a negated or warning clause ("never share", "do not
  share", "beware of", and the Tamil and Hindi equivalents). Reported as a table; adopting it is a separate
  decision because it changes rules shared with the original project.
- **R is now a development set.** Changes F and G react to it, so a pass on R after round 2 proves little. A
  fresh real set is needed for a clean claim: ordinary Tamil and Hindi SMS from more than one sender (bank
  alerts, OTPs, bills, deliveries, personal), which the owner has been asked for.
- New acceptance line **8** (reported, and required for adoption): at least 9 of the 12 R messages at low risk
  with the model alone (rule G not applied).

## Not in round 2

Other scripts, Llama writing Indian languages, any change to the original project.
