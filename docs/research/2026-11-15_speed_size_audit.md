# Speed and size audit (2026-11-15)

**Status 2026-11-21.** P1 is done for both phone types in `deploy/android/device_test.ps1` and `full_test.ps1`: dot-product phones receive only `sms_int8.pte` (1,144 MB pushed), and phones without dot product receive only the hybrid `sms_fp32.pte` (1,206 MB pushed; `sms_int8.pte` is not pushed unless `sms_fp32.pte` is missing locally). P2 is done in commit `39a80fe` (persisted integrity trust). P3 is done: hybrid model `sms_fp32_int8emb.pte` (112.0 MB vs 198.5 MB plain fp32; same label on 200/200 parity inputs, max logit difference 0.074, PC p50 211 ms vs 220 ms; Galaxy M31 cold launch: phone re-test on a fresh install pending). P5 is enabled in the release build type on 2026-11-21; the APK size is still to be measured. P4, P6 and P7 are open.

Question: where do time and bytes go in PS3 Sentinel today, and what would make it faster and smaller without hurting detection.

Every claim is marked **measured** (a number taken in this project, with where), **source** (external documentation, listed at the end) or **inference** (reasoning from measured numbers, not yet tested). The proposals were written on 2026-11-15 and the status block above records what has since been done.

## 1. Where the bytes are (measured)

Files a phone needs today (`models/`, sizes on disk):

| File | Size | Used by |
|---|---|---|
| `llama.pte` (Llama 3.2 1B SpinQuant INT4) | 1,083.3 MB | advice |
| `sms_fp32.pte` | 198.5 MB | SMS model on phones without dot product (Galaxy M31) |
| `sms_int8.pte` | 51.0 MB | SMS model on phones with dot product (Galaxy F14, moto g73) |
| `sms_vocab.txt` | 6.0 MB | SMS tokenizer (full 250,002-entry vocabulary) |
| tokenizer cache built on the phone (`sms_vocab_*.bin`) | 10.2 MB | SMS tokenizer |
| `tokenizer.model` (Llama) | 2.1 MB | advice |
| `url_cnn_v2.pte` + `vocab.json` | 1.1 MB | URL model |
| `id_map.json` | 1.0 MB | SMS tokenizer |
| **Total pushed today** | **1,343 MB** | |

Debug APK 18.7 MB. Largest entries (stored size): `libexecutorch.so` 9.1 MB (uncompressed), `classes.dex` 4.1 MB (10.0 MB raw), `libc++_shared.so` 1.3 MB, `resources.arsc` 1.1 MB (uncompressed), seven font files 1.0 MB (2.0 MB raw). The release build type has `isMinifyEnabled = false` (`android/app/build.gradle.kts`).

Git repository: pack 51.5 MiB. Tracked media is 45.9 MB in 50 files, of which 36.0 MB is 12 screen recordings (`bench/results/f14_*/*.mp4`). (Status 2026-11-24: the two `bench/results/f14_offline_*` recordings were deleted from git and `.mp4`/`.webm` were excluded from the submission packager, so tracked media is now 27.2 MB in 48 files, of which 17.3 MB is 10 screen recordings.)

Inside the SMS model: the embedding table is 79,017 rows by 384 values = 30.3 million numbers. At four bytes each that is 115.7 MB of the 198.5 MB fp32 file, and at one byte each 28.9 MB of the 51.0 MB int8 file (arithmetic from `export_q.json`: `kept_vocab` 79,017).

## 2. Where the time is (measured, phone logs of 2026-11-15)

| Step | Galaxy M31 (no dot product) | Galaxy F14 | moto g73 |
|---|---|---|---|
| Detection per SMS, code-mixed set (models + rules) | 0.19 s | 0.03 s | 0.02 s |
| SHA-256 check of `llama.pte` at every cold start | 8.3 s | not logged today | 6.0 s |
| SHA-256 check of the SMS model at every cold start | 1.2 s | not logged today | 0.25 s |
| SMS tokenizer load | 1.3 s (cache present) | not logged today | 5.9 s (first run, builds cache) |
| Llama prefix prefill after start and after each advice | 27 to 29 s | 5.1 s | 4.9 s |
| Advice (about 55 tokens) | 15 to 17 s, first token 5.3 to 6.8 s, 5.7 tokens/s | not measured today | not measured today |


SMS token length on the evaluation texts (held-out, code-mixed and three inboxes): median 40 tokens, 90th percentile 60, 99th percentile 155; 1.6 % of messages are longer than the 128-token limit and are cut.

## 3. Proposals, ranked by gain for effort

### P1. Push only the SMS model the phone can use — saves 198.5 MB or 51.0 MB

**Measured:** the app logs `sms_model_choice=sms_int8.pte dot_product=true` or `sms_fp32.pte dot_product=false` and loads one file; the other is never read. The deploy scripts push both.
**Change:** the deploy script reads the CPU features over adb and pushes one file; the app already falls back by itself.
**Gain:** dot-product phones need 1,144 MB instead of 1,343 MB (−15 %); other phones 1,292 MB. No effect on speed or accuracy. Effort: small (deploy script and manifest only).

### P2. Remember the integrity check between app starts — saves 6 to 9.5 s per cold start

**Measured:** `integrity_verify_model=llama` 8.3 s on the M31 and 6.0 s on the moto g73, plus 1.2 s and 0.25 s for the SMS model, on every cold start. The verification cache in `ModelStore.kt` lives only as long as the process (comment at line 155).
**Change:** store size, modification time and the verified hash in app-private storage; on the next start trust a file whose size and time are unchanged. The verified copies already sit in app-private storage that other apps cannot write.
**Risk:** a changed file with the same size and time is not noticed (needs root). A full re-hash can still run in the background after models are loaded.
**Status:** open owner decision since 2026-11-13 (see project notes); effort small.

### P3. Smaller fp32 SMS model for phones without dot product — about 198.5 MB to about 112 MB

**Status (done 2026-11-21):** implemented via `training/sms/export_sms.py --hybrid-fp32` producing `sms_fp32_int8emb.pte` (112.0 MB vs 198.5 MB plain fp32). Same label as plain fp32 on 200/200 parity inputs, max logit difference 0.074 (`export_q.json`), PC p50 211 ms vs 220 ms. Phone re-test on a fresh install pending.
**Measured:** 115.7 MB of the fp32 file is the embedding table. The int8 export already stores that table as int8 through a manual route (`route: torchao_linear_plus_manual_int8_embedding`).
**Inference:** a third export with the int8 embedding table and fp32 linear layers would be about 28.9 + 82.8 = 112 MB. An embedding lookup is a table read, so it does not need dot-product instructions; speed should stay near 0.19 s. Accuracy must be checked the same way as the existing exports (200-message parity and the held-out sets).
**Source:** XNNPACK's fast int8 matrix kernels use the dot-product and I8MM instructions (Arm blog); this matches the project's own Galaxy F12 measurement (2.8 to 10.4 s per message with int8 and no dot product), so int8 linear layers stay excluded on those phones.
Effort: medium (one export run in the existing WSL environment, one phone run).

### P4. Do not let the Llama prefill block detection on slow phones

**Measured:** on the M31 the background prefill holds the model lock for 27 to 29 s after app start and after each advice. An SMS arriving then waits: today's cold-start test showed a 15 s model timeout and a rule-only alert 22.7 s after arrival.
**Options (inference, both untested):** (a) on the LIGHT tier, start the prefill only when the app is in the foreground or after an idle period much longer than the present 5 s; (b) release the lock between prefill chunks so a waiting SMS runs after one chunk.
**Gain:** detection on slow phones returns to about 0.2 s in that window; also saves the energy of a 28 s four-core run after every alert when the user never opens the advice. Cost: first advice token later on LIGHT phones when the prefix is not ready. Effort: medium; needs a re-test on the M31.

### P5. Release build with code and resource shrinking — APK 18.7 MB to an estimated 12 to 14 MB

**Measured:** `isMinifyEnabled = false`; dex 10.5 MB raw; fonts 2.0 MB raw in seven files (three families); `resources.arsc` 1.1 MB; `libexecutorch.so` 9.1 MB.
**Source:** Android documentation: `minifyEnabled` with `shrinkResources` enables R8 code and resource shrinking; R8 full mode is the default since AGP 8.0 and can need keep rules for code reached by reflection. ExecuTorch documentation: a selective build (`EXECUTORCH_SELECT_OPS_FROM_MODEL`, dtype selective build) keeps only the kernels the models use; it applies to the portable and optimized kernel libraries, not to delegates such as XNNPACK.
**Inference:** R8 plus resource shrinking, limiting resources to English, two font families instead of three, and a selective ExecuTorch build should bring the APK to roughly 12 to 14 MB. The exact figure is unknown until built; the ExecuTorch JNI classes need keep rules, and every model must be loaded once on a phone with the shrunk build.
Effort: medium. A release APK is also an open hand-over item (D2).

### P6. Move screen recordings out of the repository — clone 51 MB to about 15 MB

**Measured:** 36.0 MB of the tracked files are 12 mp4 recordings (10 recordings, 17.3 MB, after the 2026-11-24 deletion noted in section 1).
**Change:** attach them to a GitHub release (or the submission folder) and link them from the docs. The clone only shrinks if history is rewritten; that could be done in the same step as removing the Kaggle username from history, before the repository goes public. Effort: small, but a history rewrite needs the owner's go-ahead.

### P7. Long messages are cut at 128 tokens (accuracy, not speed)

**Measured:** 1.6 % of evaluation messages exceed 128 tokens. Whether scams hide their request after token 128 has not been measured. A check: score those messages once with the limit at 256 on the PC and compare. The export already supports dynamic length (`dynamic_parity` in `export_q.json`), so a longer limit costs time only on long messages. Effort: small to measure.

## 4. Measured and rejected

### Cutting the SMS vocabulary below 79,017 entries

The 79,017 entries are the tokens that occur in the training corpus. Counting token use on a sample of 459,892 corpus rows and scoring unknown tokens on the evaluation texts:

| Vocabulary | Int8 file saving | Real inbox messages with an unknown token (vivo / M31 / F14) | Held-out Hinglish | Code-mixed Tamil | Held-out Marathi |
|---|---|---|---|---|---|
| 79,017 (shipped) | 0 | 0.4 / 0.2 / 1.0 % | 0.2 % | 0.0 % | 0.0 % |
| 60,000 | 7.0 MB | 4.2 / 7.2 / 9.2 % | 3.0 % | 9.8 % | 86.2 % |
| 50,000 | 10.6 MB | 13.6 / 22.2 / 14.4 % | 10.0 % | 9.8 % | 89.8 % |
| 40,000 | 14.3 MB | 29.0 / 43.6 / 40.4 % | 20.2 % | 23.0 % | 94.6 % |
| 30,000 | 17.9 MB | 50.7 / 62.2 / 58.5 % | 42.1 % | 38.0 % | 98.8 % |

Saving 7 MB already puts unknown tokens into 4 to 9 % of real inbox messages. Rejected. (Script: `data/tools/measure_vocab_use.py` in the multilang copy; the same table shows that Gujarati, Kannada, Malayalam, Odia and Punjabi text is 45 to 74 % unknown tokens even with the shipped vocabulary, which is why those languages are not claimed.)

### A pruned vocabulary file for the phone tokenizer

The phone loads all 250,002 vocabulary entries (6.0 MB, plus a 10.2 MB cache). Dropping the unused entries from the file would change how the tokenizer splits words, because the splitter chooses among all known pieces; the phone would then disagree with the Python tokenizer. Not pursued. Only the 1.0 MB `id_map.json` could be folded into the vocabulary file.

### A smaller advice model

**Source:** the ExecuTorch Llama README lists the 1B SpinQuant build at 1,083 MiB and the QAT+LoRA build as slower on its test phone (45.8 against 50.2 tokens per second). The rules of the challenge require a Llama-family model, and the owner decided on 2026-11-13 that Llama 3.2 1B stays. No smaller official build exists, so the 1.08 GB cannot be reduced within the rules.

### Faster detection


## 5. Combined effect if P1 to P6 were done (inference)

| | Today | After |
|---|---|---|
| Model files, phone with dot product | 1,343 MB | 1,144 MB |
| Model files, phone without dot product | 1,343 MB | about 1,200 MB |
| APK | 18.7 MB (debug) | about 12 to 14 MB (release) |
| Cold start to models ready, M31 | hashing adds about 9.5 s | hashing removed |
| SMS during Llama prefill, M31 | up to 15 to 23 s late | about 0.2 s |
| Repository clone | 51 MB | about 15 MB |

Suggested order: P1 and P2 (small, no accuracy risk), then P4 (the remaining slow-phone weakness), then P5 with the release APK, then P3, P6 and P7.

## Sources

- ExecuTorch kernel library selective build: https://docs.pytorch.org/executorch/0.7/kernel-library-selective-build.html
- ExecuTorch XNNPACK backend: https://docs.pytorch.org/executorch/0.7/backends-xnnpack.html
- Arm blog, LLM inference with quantized Llama models, ExecuTorch and KleidiAI: https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/llm-inference-llama-quantized-models-executorch-kleidiai
- PyTorch blog, ExecuTorch and KleidiAI: https://pytorch.org/blog/bringing-generative-ai-to-the-masses-with-executorch-and-kleidiai/
- ExecuTorch Llama example README (model size and speed table): https://android.googlesource.com/platform/external/executorch/+/HEAD/examples/models/llama
- Android developers, enable app optimization with R8: https://developer.android.com/r8
