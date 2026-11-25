# PS3 Sentinel — Architecture Rules

Binding on every change. A change that violates a rule here is rejected in review, even if it works.
Companion document: `docs/CODING_STANDARDS.md` (mechanical limits, naming, docstrings, error handling).

---

## 0. Governing question

Before adding any folder, file, class, interface, or dependency, answer in one sentence:

> What breaks today if this does not exist?

"Future flexibility", "it's cleaner", "standard practice", and "we might need it" are not answers.
If there is no answer, the thing does not get created.

---

## 1. Python module map — `sentinel/`

| File | Responsibility | Imports (from `sentinel/`) |
|---|---|---|
| `rules.py` | Loads and validates `sentinel/data/rules.json` once at import; exports `RULES`, `CUE_RULES`, `FUSION_RULES`, `DETECTOR_VERSIONS`; raises `RulesError` on missing/malformed file. | none (stdlib only) |
| `url_features.py` | URL extraction (`extract_urls`) and normalisation (`normalise_url`) from raw message text. | none (stdlib only) |
| `detectors.py` | SMS cues (`sms_cues`), URL indicators (`url_indicators`), registered domain, `UrlDetector`, `SmsDetector`, `remap_ids`. | `rules.py`, `url_features.py` |
| `fusion.py` | Fuse detector outputs + cues into `Evidence`; trusted-host checks; loads `sentinel/data/trusted_domains.txt`. | `detectors.py`, `rules.py`, `url_features.py` |
| `advisor.py` | System prompt, SMS sanitisation, prompt building, template advice, `guard`, `LlamaAdvisor` (subprocess to `llama_main`). | `fusion.py` (`Evidence`) |
| `pipeline.py` | Orchestrates URL extraction → scoring → cues → SMS detector → fusion → advisor; `analyse` never raises. | `advisor.py`, `detectors.py`, `fusion.py`, `url_features.py` |
| `cli.py` | CLI entry, detector loading (`load_detectors`), output formatting. | `advisor.py`, `detectors.py`, `pipeline.py` |
| `__main__.py` | `python -m sentinel` entry point; calls `cli.main`. | `cli.py` |
| `data/rules.json`, `data/trusted_domains.txt` | Shared detection rules and trusted-domain list, single source of truth for both platforms. | — |

**Python dependency direction:** the graph flows toward the edge — `rules.py` and `url_features.py` are leaves;
everything else depends on them transitively, ending at `cli.py`. `tests/` and `bench/` may import `sentinel/`;
nothing in `sentinel/` imports `tests/` or `bench/`.

---

## 2. Android module map — `android/app/src/main/java/org/ps3/sentinel/`

| Package / file | Responsibility | Imports (app packages) |
|---|---|---|
| `core.Rules` | Reads and validates the shared `rules.json` asset; exposes `CueRules`, `FusionRules`, `detectorVersions`. | none |
| `core.Cues` | `smsCues` — keyword + regex cue spans with offsets, using `Rules.active()`. | `core` |
| `core.Fusion` | `fuse`, `Evidence`, `TrustedDomainStore`, `isTrusted`; merges SMS/URL/cue evidence into a verdict. | `core` |
| `core.SmsTokenizer` | Hand-rolled SentencePiece-style tokenizer (normalise, pre-tokenize, Unigram Viterbi, encode). | `core` |
| `core.UrlFeatures` | `extractUrls`, `normaliseUrl`. | `core` |
| `core.UrlIndicators` | `urlIndicators`, `getRegisteredDomain`, brand/shortener/risky-TLD checks. | `core` |
| `core.UrlEncoder` | Encodes a normalised URL to the fixed-length id array the URL model expects. | `core` |
| `core.Advisor` | `SYSTEM_PROMPT`, `sanitizeSmsText`, `buildPrompt`, `templateAdvice`, `guard`. | `core` |
| `ml.ModelStore` | Model directory, manifest (`models.sha256`), integrity checks, `sha256Short`. | root (`SentinelApp`, only in `statusSummary`) |
| `ml.UrlClassifier` | ExecuTorch URL phishing scoring with indicator fallback. | `core` |
| `ml.SmsClassifier` | ExecuTorch SMS classification scoring; `SMS_LABEL_HAM/UNWANTED/SCAM`. | `core` |
| `ml.LlamaAdvisor` | Llama generation + stats parsing; calls `core.buildPrompt`/`guard`/`templateAdvice`. | `core` |
| root `SentinelApp` | `Application`; owns model init, pipeline, trusted domains, rules load on startup. | `core`, `ml` |
| root `Pipeline` | Orchestrates the detector stages; `suspend fun analyse`. | `core`, `ml` |
| `ui.MainActivity` | UI screen; reads pipeline results, shows verdicts/advice. | root, `core`, `sms` |
| `sms.SmsReceiver` | Broadcast receiver; runs `analyseFast`/`analyseFastRulesOnly` on SMS arrival. | root, `core`, `ui` |

**Android dependency direction (ideal):** `ui` / `sms` → root → `ml` → `core`, and `core` imports nothing from
other app packages. Current deviations worth fixing: `SmsReceiver` ↔ `MainActivity` reach each other,
and `ml.ModelStore` reaches root `SentinelApp` (only inside `statusSummary`). `core` must stay pure
Kotlin/JVM so it can be reasoned about and unit-tested without Android.

---

## 3. Allowed import direction

Python (`sentinel/`):

```
tests/ bench/  ──may import──►  sentinel/
                                      ▲
                                      │
  cli.py  pipeline.py  advisor.py   fusion.py   detectors.py   url_features.py   rules.py
     ▲         ▲          ▲           ▲           ▲              ▲                 ▲
     └─────────── depends on (transitively) ────────────────────────────────────────┘
```

Nothing in `sentinel/` imports `tests/` or `bench/`. Runtime optional deps (`torch`, `executorch`,
`transformers`) are imported lazily inside `detectors.py` / `advisor.py` methods, never at module top.

Android:

```
 ui/   sms/     root  ml   core
  ▲     ▲       ▲     ▲    ▲
  │     │       │     │    └── imports nothing from app packages
  │     │       │     └────────► core  (ModelStore → root only in statusSummary)
  │     │       └───────────────► core + ml
  │     └───────────────────────► root + core + ui  (deviation: reaches ui)
  └─────────────────────────────► root + core       (deviation: reaches root)
```

Enforcement is by grep (see §5), matching BhashaBridge `DEPENDENCY_RULES.md`: no new Gradle modules
yet; compiler-enforced boundaries are justified only if a boundary violation reaches `main`.

---

## 4. Python ↔ Kotlin duplicated logic and its ties

The same detection logic exists on both platforms. For each pair: the Python side, the Kotlin side,
what ties them together, and the status. `TIE` = a test or shared source keeps them in sync.

| # | Logic | Python side | Kotlin side | Tie mechanism | Status |
|---|---|---|---|---|---|
| 1 | Cue keywords/regexes + fusion weights | `sentinel/data/rules.json` read by `sentinel/rules.py` | Same asset read by `core/Rules.kt` (wired via `assets.srcDir "../../sentinel/data"`) | `tests/fixtures/parity_cases.json` + `tests/make_parity_cases.py` replayed by `ParityTest` (cues, fusion, label, level, risk); `CuesTest`/`FusionTest` load `sentinel/data/rules.json` directly | TIE |
| 2 | URL extraction & normalisation | `sentinel/url_features.py` (`extract_urls`, `normalise_url`) | `core/UrlFeatures.kt` + `core/UrlIndicators.kt` | `ParityTest` asserts `extracted_urls`, `normalised_urls`, and URL indicators match the Python reference per case | TIE |
| 3 | Trusted domains list | `sentinel/data/trusted_domains.txt` (loaded by `sentinel/fusion.py`) | Asset `sentinel/data/trusted_domains.txt` loaded by `SentinelApp` into `core.TrustedDomainStore` | Single source of truth: `android/app/build.gradle.kts` packages `sentinel/data` via `assets.srcDir`, so one file serves both platforms; `ParityTest` loads the Python file directly | TIE |
| 4 | URL phishing threshold (0.5) | `sentinel/data/rules.json` `fusion.url_phishing_label_threshold = 0.5` | `ml/UrlClassifier.kt` `URL_PHISHING_THRESHOLD = 0.5` | `ml/MlConstantsTest.testUrlThresholdMatchesPython` ties the constant to `rules.json` | TIE |
| 5 | SMS label order (ham=0, unwanted=1, scam=2) | `sentinel/detectors.py` `SmsClassifier.predict` builds probs in that order | `ml/SmsClassifier.kt` `SMS_LABEL_HAM/UNWANTED/SCAM` | `ml/MlConstantsTest.testSmsLabelOrderMatchesPython` reads `sentinel/detectors.py` | TIE |
| 6 | Llama system prompt | `sentinel/advisor.py` `SYSTEM_PROMPT` | `core/Advisor.kt` `SYSTEM_PROMPT` | `tests/test_pipeline.py::test_system_prompt_matches_kotlin` compares byte-for-byte | TIE |
| 7 | Detector versions / model filenames | `sentinel/data/rules.json` → `sentinel/fusion.py` `DETECTOR_VERSIONS` | Same asset → `core/Fusion.kt` `Rules.active().detectorVersions` | Shared `rules.json` source of truth (construction tie); no dedicated assertion test that the two reads match | TIE (source), no dedicated test |
| 8 | SMS tokenizer | Python uses `transformers.AutoTokenizer` (via `SmsDetector`) | `core/SmsTokenizer.kt` (hand-rolled Unigram Viterbi) | `SmsTokenizerTest` fixture (`sms_tok_fixture.json`, ~300 messages) checks Kotlin encodes match Python-generated ids/masks at ≥98% | TIE |
| 9 | Advisor guard / template advice | `sentinel/advisor.py` `guard` / `template_advice` / `build_prompt` | `core/Advisor.kt` `guard` / `templateAdvice` / `buildPrompt` | `tests/fixtures/advisor_cases.json` (50 cases: refusals, contradictions, click/callback/threat sentences, Hinglish, empty/long/special-token output) + `tests/make_advisor_cases.py` replayed by `AdvisorParityTest` (Kotlin guard/template must match Python text and flags); Python staleness asserted by `tests/test_advisor_parity.py` | TIE |

All rows TIE; the previous row 9 gap is closed by `AdvisorParityTest`.

---

## 5. Enforcement (grep)

Run from the repo root. Each command must print nothing (exit 0 with no matches):

```powershell
# Python: nothing in sentinel/ may import tests/ or bench/
grep -rn "import tests\|from tests\|import bench\|from bench" sentinel/ | findstr /v "^$"   # must be empty

# Android: core/ must not import app packages (ui, ml, root, sms)
grep -rn "^import org\.ps3\.sentinel\.(ui|ml|root|sms)" android/app/src/main/java/org/ps3/sentinel/core/ | findstr /v "^$"   # must be empty

# Android: nothing outside core/ may reference ExecuTorch model classes directly
grep -rn "org.pytorch.executorch" android/app/src/main/java --include=*.kt | findstr /v "/ml/"   # must be empty
```

These are the grep equivalents of BhashaBridge `DEPENDENCY_RULES.md` §Enforcement and are run by
`scripts/check.ps1` / `scripts/check.sh`.
