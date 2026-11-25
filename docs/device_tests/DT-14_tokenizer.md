# DT-14: Kotlin vs Python tokenizer mismatch — fixed

Status: FIXED. 1000 bench messages compared, 0 mismatches after fix (3 before).

What was compared:
- Messages: all 1000 lines of `bench/bench_messages.txt` in file order.
- Reference: `bench/heldout/calib_20261108/token_ids_20261108.jsonl` (1000 JSON lines,
  copied to `android/app/src/test/resources/sms_tok_bench_reference.jsonl`), produced on
- Field mapping: each JSON line is `{"line", "text_hash", "input_ids"}` with `line` the
  0-based index in dump_probs' filtered list
  `[ln.rstrip("\n") for ln in open(...).read().splitlines() if ln.strip()]`.
  `bench_messages.txt` is 1000 CRLF-delimited lines with no empty/whitespace-only lines,
  no leading/trailing spaces and no other line separators, so the filter is the identity
  and `line` equals the file line number. The Kotlin test (`SmsTokenizerBenchParityTest`)
  splits the decoded text on `\n` + trailing `\r`, applies the same strip filter, and
  verifies the mapping by recomputing `text_hash` (SHA-1 of
  `" ".join(text.strip().lower().split())`) for every line.
  `tokenizer([text], padding=False, truncation=True, max_length=128)` and then remaps
  through `id_map.json`. The reference is therefore unpadded and post-remap (model ids
  0..72861, lengths 6..128, 18 at exactly 128). The Kotlin test applies the identical
  `id_map` after `SmsTokenizer.encode(text, pad = false)` and compares the unpadded
  id lists exactly. This mirrors `SmsClassifier.predict` on Android and
  are byte-identical to the `sms_v5q` copies the test loads from the repo path and
  the `sms_vocab.txt` test resource. `bench_messages.txt` is read from the repo
  path, so no test-resource copy was needed.

Result:
- Before fix: 997 / 1000 matched, 3 mismatched at `line` 201, 401, 467
  (0-based, same indices as the earlier worker count).
- After fix: 1000 / 1000 matched, 0 mismatched. No allow-list.
- Existing fixture parity (`SmsTokenizerTest.testFixtureParityAgainstPythonTokenizer`,
  `sms_tok_fixture.json`): 300 / 300 exact (100%) after fix.

Root causes and fixes (all in `SmsTokenizer.kt`):
- Line 201 (U+FFFD replacement character, ×2 in `It�s` / `ph�`): Kotlin kept
  U+FFFD, which is absent from the vocab, so Viterbi emitted one UNK per
  U+FFFD (expected len 44, Kotlin len 46). The Python reference shows `It�s`
  as `▁It` + `▁s` and no UNK, i.e. U+FFFD acts as a word separator.
  Fix: `replaceWhitespaceChars` maps `\uFFFD` to a space (like the other
  whitespace controls).
- Line 401 (U+009F in `Ã°Â\x9fÂ\x93Â\x8aTrading...`): U+009F is absent from the
  vocab with no containing piece, so Kotlin emitted UNK (expected len 16,
  Kotlin len 17) where Python emits nothing. Python deletes U+009F without a
  word boundary (reference concatenation has no `▁Â`; other C1 controls
  U+0093/U+008A/U+0095 etc. are in the vocab and kept by both). Fix:
  `replaceWhitespaceChars` drops `\u009F` (appends nothing).
- Line 467 (`???????????` runs): the segmentations `▁`+`????`+`???????` and
  `▁`+`???????`+`????` are an exact tie in full tokenizer.json precision
  (both -30.097941160202026) but differ by 3.5e-15 with the 8-decimal scores
  stored in `sms_vocab.txt` (-30.09794116 vs -30.097941159999998), so Kotlin
  picked the latter while Python picks the former (first-path wins on an
  exact tie). Fix: Viterbi now requires an improvement greater than
  `viterbiEps = 1e-7` to replace the best score, emulating first-wins on
  near-ties from score rounding.

Python and Kotlin twins stay in parity: the only behaviour changes are the
three normalizer/Viterbi fixes above; padding, truncation (126 sequence
tokens + BOS/EOS at 128), byte fallback (off), unknown-piece fusion and
UNK scoring are unchanged.
