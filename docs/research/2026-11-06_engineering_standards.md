# Engineering standards for PS3 Sentinel (Python + Kotlin)

**Repo:** `C:\Users\user\arm-ps3` (Bharat AI-SoC Challenge 2026-27, PS3).  
**Topic:** engineering standards so the code stays human-readable and a change in one file cannot silently break the project.  
**Video deadline:** 23 Nov 2026 (today is 2026-11-06).  
**Status:** research only — no files edited except this one.

## Source key

Every idea is tagged: `measured` (number read from this repo), `sourced` (URL or `.ref/bhashabridge/<FILE.md>`), or `inference` (my conclusion, not a measurement).

## Short summary

The repo works (67 pytest pass / 1 skipped; Android `assembleDebug` BUILD SUCCESSFUL) but has no written coding standard, no module/dependency rules, no single check command, no pre-commit gate, and the same detection logic lives twice (Python and Kotlin) with no parity test for most of it. The 2026-11-06 review logged 10 security findings and 6 fragility findings; several are unfixed. Proposals below are ranked by gain/effort. All seven fit before the 23 Nov 2026 video deadline; the security and parity items are gating for a credible demo because NFR-07 (no egress/privacy) and FR-14 (stable detector interface) are judged live on device.

## Proposals

### P-01 Adopt a written coding standard for Python and Kotlin
- **What:** Adopt a small, enforced standard (one doc, `docs/CODING_STANDARDS.md`) covering file/function size, naming, nullability, comments, and KDoc format, for both `sentinel/` (Python) and `android/` (Kotlin).
- **Why it matters:** Judges read code; a 961-line god class was BhashaBridge V3's fatal defect (one reasonable diff at a time, no tripwire). A hard size limit trips before anyone's judgement has to. This is the engineering-standards topic itself, and it protects FR-14 (detector interface must stay stable as Phase 2 adds a network detector).
- **Evidence:**
  - `measured`: `sentinel/pipeline.py:31` `analyse` is 136 lines; `sentinel/fusion.py:118` `fuse` is 134 lines; `sentinel/advisor.py:167` `guard` is 94 lines — all above the proposed 60-line function cap. Read directly.
  - `sourced`: BhashaBridge `CODING_STANDARDS.md` §1 sets hard limits: file 400 lines, function 60 lines, 5 parameters, nesting depth 4, 120 chars/line. `ARCHITECTURE_RULES.md` R3.1 (one responsibility, one sentence, no "and"), R10.1 (banned class suffixes: `Manager`, `Helper`, `Util`, `Service`, `Handler`, `Processor`, `Controller`, `Impl`, `Base`, `Abstract`), §3 comment format ("explain why, never what"; `// ponytail:` for deliberate shortcuts), §5 nullability (`!!` banned; `lateinit` only for Android-injected views), §6 sealed result types (failure never in a success-typed value). `PROJECT_STRUCTURE.md` root package 3-file cap.
  - `inference`: applying a 60-line function cap to `sentinel/` forces `analyse` and `fuse` to split into stage functions, which is exactly where a silent single-file change could otherwise break fusion verdicts.
- **Expected gain:** qualitative — review becomes bounded; diffs stay reviewable. BhashaBridge V4 cut ~600 lines of dead/inert code by applying the same limits (`LESSONS_FROM_V3.md` L4, `CODE_SIMPLIFICATION_AUDIT.md` §1).
- **Effort:** 8 hours. Files: new `docs/CODING_STANDARDS.md`; no source changes required to adopt (enforcement is in review + check script in P-02).
- **Risk:** standard ignored if not automated — mitigated by P-02/P-03.
- **Before 23 Nov 2026:** Yes.

### P-02 Module boundaries and allowed dependencies (one file, enforced by grep)
- **What:** Write `docs/DEPENDENCY_RULES.md` stating which package may reference which, and a list of allowed dependencies per package. Enforce in review with grep (no new Gradle modules — build cost not justified yet).
- **Why it matters:** Prevents the Android `ui/` layer reaching into ExecuTorch/model code and the Python pipeline importing test-only helpers. Keeps the detector interface (FR-14) the only seam Phase 2's network detector plugs into. Matches NFR-08 (CPU/NPU placement documented and separate).
- **Evidence:**
  - `sourced`: `.ref/bhashabridge/DEPENDENCY_RULES.md` — graph `ui → {speech, mt, root}`, `speech/mt → root`, `bench → reads any, imported by none`; D1 dependencies point downward, D2 `speech`/`mt` never reference each other, D3 no cycles, D4 `bench` observes only via an inline `BuildConfig.DEBUG`-gated `Metrics` (zero cost in release). Enforcement: three `grep -rn` commands must be empty (`DEPENDENCY_RULES.md` §Enforcement).
  - `measured`: Android `android/app/build.gradle.kts` already scopes ExecuTorch + kotlinx-coroutines + AndroidX in `dependencies`; Python `sentinel/` imports only stdlib + `executorch`/`torch`/`transformers` at runtime. No current module boundary doc exists.
  - `inference`: the natural Python mapping is `sentinel/` (runtime) imports `sentinel/rules.py` (shared config) only; `tests/` and `bench/` may import `sentinel/`; nothing in `sentinel/` imports `tests/` or `bench/`.
- **Expected gain:** qualitative — a cross-cutting change (e.g. execution-provider switch) becomes a single-package edit instead of a repo-wide hunt (BhashaBridge Phase 7 touched 2 files because ONNX was confined to `mt/`, `DEPENDENCY_RULES.md` §What this buys).
- **Effort:** 6 hours. File: new `docs/DEPENDENCY_RULES.md` (plus references in `docs/CODING_STANDARDS.md`).
- **Risk:** grep enforcement is manual; a boundary violation can reach `main` before review catches it. Mitigation: make the check script in P-02 (combined with P-03) run the greps.
- **Before 23 Nov 2026:** Yes.

### P-03 One-command check script: run all tests and lints
- **What:** Add `scripts/check.py` (Python, stdlib only) that runs: `python -m pytest -q` on `tests/`, plus the dependency-boundary greps and a file/function size scan over `sentinel/` and `android/**/*.kt`. Print PASS/FAIL and exit non-zero on failure. Document that no linters are installed (see Evidence) — the script uses only pytest + stdlib, so nothing needs installing.
- **Why it matters:** Judges need one reproducible command; CI/absent-CI, `scripts/check.py` is the gate that keeps a one-file change from silently breaking the other platform (the Python/Kotlin parity problem the 11-06 review documents). Directly supports FR-14 (dummy detector registers without changing fusion/UI) and NFR-09 (no regressions in soak).
- **Evidence:**
  - `inference`: because no linter is installed and installing anything is prohibited for this task, the check script must wrap pytest + stdlib checks; adding real linters (ruff/ktlint) is a post-video follow-up, not a blocker.
- **Expected gain:** one command (`python scripts/check.py`) replaces "remember to run pytest and the Android unit tests"; catches the skipped-torch test gap and untested detector loading (review P6).
- **Effort:** 6 hours. File: new `scripts/check.py`; invoked from repo root.
- **Risk:** Android unit tests require the Gradle wrapper (works offline if cached); script must not fail hard when Gradle is unavailable — degrade to a warning, not a hard fail, for the Kotlin half.
- **Before 23 Nov 2026:** Yes.

### P-04 Pre-commit hook proposal
- **What:** Propose (do not install) a `.pre-commit-config.yaml` plus a repo-local hook `scripts/pre_commit_check.py` that runs `scripts/check.py` on staged Python files and the Kotlin size/grep checks on staged `.kt` files. Hook is opt-in until a linter is available; enforced by review meanwhile.
- **Why it matters:** Catches the "small, defensible diff" problem before commit (BhashaBridge `MainActivity` grew 300 → 600 → 961 lines with no single commit looking too large, `LESSONS_FROM_V3.md` L1). A bad commit is the cheapest thing to prevent and the most expensive to bisect.
- **Evidence:**
  - `sourced`: BhashaBridge `ARCHITECTURE_RULES.md` R14.1 (one fix, one commit), R14.2 (re-verify after each commit), R14.3 (Conventional Commits; `perf:` commits need before/after numbers). `CONTRIBUTING.md` §Commit conventions (same).
  - `measured`: no `.pre-commit-config.yaml` or `.git/hooks/pre-commit` exists in the repo (checked `.gitignore`/root listing).
  - `inference`: since pre-commit isn't installed and we must not install tooling, the proposal is a committed config file plus a review rule ("run `scripts/check.py` before committing"), active immediately without installation.
- **Expected gain:** qualitative — most parity regressions (FRAG-01/02/04) are caught at commit time rather than in the demo video.
- **Effort:** 4 hours. Files: new `.pre-commit-config.yaml`, `scripts/pre_commit_check.py`.
- **Risk:** hooks can be bypassed (`--no-verify`); review is the real enforcement.
- **Before 23 Nov 2026:** Yes.

### P-05 Tie the duplicated Python/Kotlin logic by test or shared data file
- **What:** The same detection logic exists in both languages. For each copy, add either (a) a cross-language parity test or (b) make one side the source of truth copied into the other at build time with a byte-identity check.
- **Evidence (all `sourced` from the verified 11-06 reviews):**
  - `security.md` FRAG-01: URL phishing threshold `0.90` in `android/.../ml/UrlClassifier.kt:15` and `sentinel/detectors.py:217`, no test ties them.
  - `security.md` FRAG-02: SMS label order `0=ham, 1=unwanted, 2=scam` in `SmsClassifier.kt:68-72` and `detectors.py:340-342`, no shared constant or parity check.
  - `security.md` FRAG-03: URL normalise/extract diverges, `sentinel/url_features.py:20-80` vs `UrlFeatures.kt:12-110` (different fallback for malformed hosts).
  - `security.md` FRAG-04: `sentinel/data/trusted_domains.txt` vs `android/app/src/main/assets/trusted_domains.txt`, two copies, no byte-identity test.
  - `android_app.md` F1/F4: cue/fusion tables diverge — Python has `app_install` + time-bound urgency regex + `collect_pin_score`/`app_install_score`; Kotlin `Cues.kt`/`Fusion.kt` lack them (B1-B4).
  - `android_app.md` F2: `detectorVersions`/model filenames duplicated in `Fusion.kt:138-143`, `ModelStore.kt:9-17`, `sentinel/fusion.py:155-160`.
  - `sourced` (good pattern to copy): the system prompt is already compared byte-for-byte (`test_system_prompt_matches_kotlin`) and the Kotlin SMS tokenizer is parity-tested on 300 messages (`docs/engineering_report.md` §1) — these are the only two ties that exist; everything else is untied.
- **Effort:** 10 hours. Files: `tests/test_cross_language_parity.py` (new); Kotlin JVM tests in `android/app/src/test/` (new); possibly `sentinel/data/rules.json` as single source if not already (verify `rules.py:14` reads `data/rules.json`).
- **Risk:** Kotlin side lacks a test device in CI; JVM tests run on the dev machine via Gradle (already works).
- **Before 23 Nov 2026:** Yes (tight but doable; start with threshold + label order + trusted domains, which are data-level and easiest).

### P-06 Simplify the 10 hardest-to-read functions (concrete plan)
- **What:** Split or rewrite the 10 least-readable functions below so each is under ~60 lines, has one responsibility, and is covered by a test that can fail. Order by risk (functions whose misreading changes a verdict first).
- **Why it matters:** Readable code is reviewable code; the engineering report and reviews are the artefacts judges inspect. Unreadable fusion/guard code is where `risk >= 0.7` boundaries get silently moved (review P8/P10).
- **Evidence (`measured` = read directly; `sourced` = review line numbers):**
  1. `sentinel/pipeline.py:31` `analyse` — 136 lines, six stages, nested try/except, swallows exceptions into a ham fallback. Plan: split into `extract_urls_safe`, `score_urls`, `score_sms`, `fuse_evidence`, `advise`; keep the "never raise" contract at the top only. Covered by `tests/test_pipeline.py` (can fail — good).
  2. `sentinel/fusion.py:118` `fuse` — 134 lines, URL processing + SMS/URL/cues/combo + label/level + indicators. Plan: extract `_process_urls`, `_cue_score`, `_combo_score`, `_label_and_level`; delete the dead `(has_high_untrusted and has_cred_pay_cue)` disjunct (review P8) and the unused `text` parameter. Boundary tests missing (review P10) — add parameterised tests at 0.399/0.4/0.401 and 0.699/0.7/0.701.
  3. `sentinel/advisor.py:167` `guard` — 94 lines doing certainty/contradiction/click/threat/steps. Plan: split into `normalize_certainty`, `check_contradiction`, `filter_sentences`, `backfill_steps`; fix the order-dependent adverb bug and add the `unwanted` branch (review P5).
  4. `sentinel/cli.py:135` `main` — 63 lines mixing argv defaulting, input gathering, detector loading, per-message output, JSON formatting. Plan: extract `gather_messages`, `load_detectors` (already separate), `format_one_message`.
  5. `sentinel/detectors.py:122` `sms_cues` — recompiles a regex per keyword per message; nested loops. Plan: compile patterns once at import (the rules module already compiles; `sms_cues` re-compiles) and return precompiled matches.
  6. `sentinel/detectors.py:245` `remap_ids` — recursion + nested ternary + torch/numpy branching in one function. Plan: split into `_remap_tensor`, `_remap_sequence`, `_remap_scalar`.
  7. `sentinel/url_features.py:48` `extract_urls` — dense regex + `rstrip` chain + host split. Plan: keep the regex (it's correct and tested) but name the intermediate steps; the block is small enough to stay if each line is obvious.
  8. `android/app/src/main/java/org/ps3/sentinel/core/Advisor.kt:78` `guard()` — ~120 lines, several responsibilities (review android_app.md R1, `verified`). Plan: split into `refusalCheck`, `contradictionCheck`, `sentenceFilter`, `stepBackfill` mirroring the Python `guard` split.
  9. `android/app/src/main/java/org/ps3/sentinel/ml/LlamaAdvisor.kt:155` `parseLlamaStats` — ~60 lines, two branches (review android_app.md R2, `verified`). Plan: extract two parsers, dispatch on `hasTimestamps`.
  10. `sentinel/cli.py:65` `load_detectors` — 35 lines, silent stderr swallow, never directly tested (review P6). Plan: return a `DetectorLoadResult` (sealed: loaded / skipped with reason) instead of printing; add a test building a valid/invalid pte stub.
- **Expected gain:** qualitative + testable: each function becomes reviewable in one screen and each split gains a failing-if-broken test.
- **Effort:** 16 hours (the largest item; sequence after P-01/P-02 so the size cap justifies the splits).
- **Risk:** splitting changes line numbers referenced by tests; update `tests/test_pipeline.py` accordingly. Behavior must stay identical — use the existing tests as the parity gate (BhashaBridge `CODING_STANDARDS.md` §11 parity idea).
- **Before 23 Nov 2026:** Yes, but sequence P-01–P-05 first; treat P-06 as "as time permits" after the video script is locked.

### P-07 Security hardening still missing after the 11-06 review
- **Why it matters:** NFR-07 (no egress/privacy) and FR-09 (never fetch a URL) are demonstrated live in the video; a tampered `.pte` or a prompt-injection attack on the Llama advisor invalidates the whole "on-device, trustworthy" story judges score.
- **Evidence (`verified` findings still unfixed):**
  - `security.md` SEC-01 (high): model files loaded from external storage with no integrity check — `ModelStore.kt:9-17`, `SmsClassifier.kt:42`, `UrlClassifier.kt:24`, `LlamaAdvisor.kt:53`. Fix: ship SHA-256/signed manifest in app assets, refuse mismatched hashes.
  - `security.md` SEC-02 (high): prompt injection — raw SMS interpolated into the Llama chat template; `sentinel/advisor.py:40-48` / `Advisor.kt:23-33`. `sanitize_sms_text` exists (`advisor.py:38`) but the finding says escaping/length cap must be verified end-to-end; cap prompt length and neutralise control tokens before `build_prompt`/`buildPrompt`.
  - `security.md` SEC-03 / `android_app.md` S1 (medium): notification exposes full SMS body — `SmsReceiver.kt:108-128`. Fix: redacted preview (sender + risk only).
  - `security.md` SEC-04 / `android_app.md` S2 (medium): exported share target, no size limit — `AndroidManifest.xml:19-24`, `MainActivity.kt:55-75`. Fix: cap accepted input length.
  - `security.md` SEC-05 / `android_app.md` S4 (low): logcat records raw URLs — `UrlClassifier.kt:52`, `Pipeline.kt:145-148`. Fix: log hash/redacted form only.
  - `security.md` SEC-06 / `android_app.md` S5 (low): `android:allowBackup="true"` — `AndroidManifest.xml:8`; Android docs recommend `false` for apps with sensitive data (`https://developer.android.com/identity/data/autobackup`).
  - `security.md` SEC-08 (low): unsafe deserialisation in training scripts — `torch.load` without `weights_only=True` in `training/sms/export_sms.py:136,203`, `train_sms.py:907`, `training/url/train_url.py:261-262`, `training/url_v2/train_url_v2.py:556-557`.
  - `security.md` SEC-09 (low): unbounded worker thread per SMS broadcast — `SmsReceiver.kt:33-52`. Fix: single-threaded executor/coroutine with backpressure.
  - `measured` (already fixed, do not re-open): SEC-07 `.gitignore` secrets — the current `.gitignore` already lists `kaggle.json`, `.env`, `*.pem`, `*.key`, `id_rsa*`, `secrets/` (read directly), so this finding is closed.
- **External sourcing:** Android `allowBackup` default `true` and recommendation to set `false` for sensitive apps — `https://developer.android.com/identity/data/autobackup`. ExecuTorch runs on Arm CPUs via the XNNPACK backend, which can call Arm KleidiAI micro-kernels — `https://docs.pytorch.org/executorch/main/backends-xnnpack.html` and `https://learn.arm.com/courses/executorch-on-arm/next-steps/further-learning/next-steps` (context for why model integrity matters: the `.pte` is the trusted compute artifact).
- **Expected gain:** converts 9 unfixed verified findings into fixed or mitigated; directly supports the offline/privacy demo (NFR-06/07).
- **Effort:** 14 hours spread across AndroidManifest + 4 Kotlin files + advisor.py + 4 training scripts + deploy script.
- **Risk:** model hash-check adds startup latency (measure; keep under NFR-02's 50 ms detector budget — the hash check is one-time at load, not per-message).
- **Before 23 Nov 2026:** Yes — this is gating for the video; prioritize SEC-01, SEC-03, SEC-04, SEC-06 first.

## Ranking (gain ÷ effort)

| Rank | ID | Title | Effort | Fits before 23 Nov 2026? | Notes |
|---|---|---|---|---|---|
| 1 | P-01 | Coding standard (Python + Kotlin) | 8 h | Yes | Foundation; enables P-06 splits |
| 2 | P-03 | One-command check script | 6 h | Yes | No linters installed — stdlib + pytest only |
| 3 | P-04 | Pre-commit hook proposal | 4 h | Yes | Opt-in until tooling installed |
| 4 | P-02 | Module boundaries + dependency rules | 6 h | Yes | Protects FR-14 / NFR-08 |
| 5 | P-05 | Tie duplicated Python/Kotlin logic | 10 h | Yes | Start with threshold/label order/trusted domains |
| 6 | P-07 | Security hardening (unfixed findings) | 14 h | Yes | Gating for the video demo (NFR-06/07) |
| 7 | P-06 | Simplify 10 hardest-to-read functions | 16 h | Partial | Do after P-01/P-02; "as time permits" |

Suggested order of work: P-01 → P-03 → P-05 (threshold + label order + trusted domains first) → P-07 (SEC-01/03/04/06) → P-04 → P-02 → P-06.

## Adoption note

All rules above are written as enforceable constraints (numbers, banned lists, required formats), not descriptions — following BhashaBridge `ARCHITECTURE_RULES.md` R15 (a rule that cannot be changed gets routed around; amendments are committed separately with `docs:`). No file except this one was created or edited in this session; no git state changed, no servers started.
