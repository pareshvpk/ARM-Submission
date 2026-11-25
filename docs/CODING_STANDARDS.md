# PS3 Sentinel — Coding Standards (Python + Kotlin)

Mechanical rules for `sentinel/` (Python) and `android/app/src/main/java/org/ps3/sentinel/` (Kotlin).
Where a rule has a number, violating it is visible in review or in `scripts/check.ps1` / `scripts/check.sh`.

Adapted from the BhashaBridge V4 standards; kept short and practical. Amendments are committed separately
with `docs:` and never silently ignored.

---

## 0. Size limits

| Unit | Limit | Enforcement |
|---|---|---|
| File | **400 lines** | hard |
| Function | **60 lines** | hard |
| Function parameters | **5** | soft — 6+ needs a reason in review |
| Nesting depth | **4** | hard |
| Line length | **120 chars** | hard |

Limits count real code — docstrings/KDoc and blank lines excluded.

**Why a hard number.** A god class never has one commit where it "became too large". It crosses
300, then 600, then 961, and each individual diff looks small and defensible. A number trips before
anyone's judgement has to.

Hitting a limit is a question, not an instruction: split a second responsibility, delete dead code,
or record in review that the thing is genuinely one cohesive responsibility.

---

## 1. Documentation format

### Python — docstrings

Every public module, class, and function gets a docstring. The first line is a one-sentence summary
with no "and"; needing "and" means the unit has two responsibilities. Follow the summary with a
blank line and the `Args:` / `Returns:` / `Raises:` sections only when they add information the
signature does not already carry.

```python
def fuse(text, sms_result, url_results, cues) -> Evidence:
    """Fuse detector outputs and cue spans into one Evidence object.

    Args:
        text: original message (kept for pipeline compatibility; fusion does not read it).
        sms_result: SMS classifier output, or None when no SMS model is loaded.
        url_results: list of URL detector outputs.
        cues: list of cue spans from sms_cues.

    Returns:
        Evidence with label, risk, level, and indicators.
    """
```

### Kotlin — KDoc

Every class gets exactly these four headings, in this order, nothing else:

```kotlin
/**
 * Purpose:  Decodes token ids to text using the target vocabulary.
 * Owns:     Nothing. Borrows the vocabulary map.
 * Lifetime: Process
 * Thread:   single-threaded — reuses preallocated buffers.
 */
```

- **Purpose** — one sentence, no "and".
- **Owns** — what it creates and destroys, or the literal word `Nothing`. Never blank.
- **Lifetime** — `Process` | `Screen` | `View`.
- **Thread** — which dispatcher, and whether confinement is load-bearing.

Public functions get KDoc only when the signature is not self-explanatory. `fun release()` does not
need a comment saying it releases.

---

## 2. Comment format

**Explain why. Never what.**

```kotlin
// BAD  — restates the code
// loop through tokens and add them
// GOOD — explains a non-obvious decision
// Single lock: two concurrent translations would corrupt the shared decode buffers.
```

**Constants carry unit and rationale:**

```python
# ms — Llama emits partials every ~100ms; 250 keeps the advisor from flooding prompt construction.
MAX_SMS_TEXT_CHARS = 500
```

**Deliberate simplifications are marked**, naming the shortcut and its upgrade path:

```python
# ponytail: linear scan over the keyword list per message. Fine at a few dozen keywords;
# revisit if the rules file grows past a few hundred entries.
```

**Banned:** commented-out code (git remembers), `TODO` without an owner and a phase number,
decorative separator banners, comments that restate a rule in this document.

---

## 3. Naming

| Thing | Convention | Example |
|---|---|---|
| Class | `PascalCase`, a noun that says what it **is** | `UrlDetector` |
| Function (Python) | `snake_case`, verb first | `extract_urls()` |
| Function (Kotlin) | `camelCase`, verb first | `extractUrls()` |
| Boolean | `is` / `has` / `can` prefix | `isLoaded` |
| Constant | `SCREAMING_SNAKE`, unit in the name | `MAX_SMS_TEXT_CHARS` |
| Module / package | lowercase, no underscores | `sentinel.detectors` |

**Banned class suffixes:** `Manager`, `Helper`, `Util`, `Service`, `Handler`, `Processor`,
`Controller`, `Impl`, `Base`, `Abstract`. A `Manager` suffix makes "and it also copies files" feel
natural; precise names resist scope creep.

**Abbreviations:** keep them domain-standard and spelled out at least once nearby. Never invent
`cfg`, `impl`, `req`, `res`, `mgr`.

---

## 4. Named constants

Magic numbers are banned in logic. Every threshold, weight, cap, timeout, and length limit is a
named constant with a unit and the reason for its value:

```kotlin
// 0.5 — validation FPR on url_v2 held-out set. Keep in sync with
// sentinel/data/rules.json fusion.url_phishing_label_threshold (0.5) and
// ml/UrlClassifier.kt URL_PHISHING_THRESHOLD = 0.5; see MlConstantsTest.
const val URL_PHISHING_THRESHOLD: Double = 0.5
```

Real silicon does not match the datasheet, so a value buried in an expression cannot be swept or
tuned. Constants live at the top of the file that owns them, never inside an expression.

---

## 5. Error handling

**Failure is never encoded in a success-typed value.** A function typed to return a risk score or
advice string must not return a failure message in its place; the caller cannot tell success from
failure and will render or log the failure as if it were a real result.

- Catch narrowly: `except (OSError, json.JSONDecodeError)` — never a bare `except:` or
  `catch (e: Exception)` around a large block, which hides NPEs and stack traces.
- Never catch `Throwable`, `Error`, `OutOfMemoryError`, or `KeyboardInterrupt` / `CancellationException`.
- **Never swallow an exception silently.** Every `catch` that does not re-raise must log at warning
  level **naming the detector and the reason it is safe to continue**:

```python
except Exception as error:
    logging.getLogger("PS3Sms").warning(
        "url detector %s failed on input, falling back to indicators: %s",
        detector_name, error,
    )
```

```kotlin
catch (e: Exception) {
    Log.w(TAG, "URL model failed on ${shortDigest(url)}, using indicators: ${e.message}", e)
}
```

- Validate at trust boundaries — imported files, model outputs, SMS text, URLs. This rule is exempt
  from the simplicity rule: never remove validation to shorten code.

---

## 6. Untrusted input

SMS text and URLs are attacker-controlled. Treat them as untrusted everywhere:

- Never interpolate raw SMS text into a command, a shell call, or a model prompt without sanitising
  delimiters and control tokens first (see `sentinel/advisor.py` `sanitize_sms_text` and Kotlin
  `Advisor.sanitizeSmsText`).
- Cap input length before it reaches any model (`MAX_SMS_TEXT_CHARS = 500`).
- Never log raw SMS text or raw URLs in release builds. Log a hash or a redacted form only
  (see `Pipeline.shortDigest` / `sha256Short`).
- Malformed input must become evidence, never an exception that aborts the whole analysis
  (`url_indicators` returns `["unparseable_url"]` instead of raising).

---

## 7. Logging

- One tag per subsystem (`PS3Sms` on Android, module-level logger name in Python).
- User SMS text and URLs are never logged in release builds — hash or redact only.
- Debug logging is guarded behind a debug flag; never format strings inside a hot decode/detect loop.

---

## 8. Formatting

- Python: 4-space indent, no trailing whitespace, one top-level concern per file.
- Kotlin: official Kotlin style, 4-space indent, no tabs, no wildcard imports, one top-level class
  per file whose filename matches the class, expression bodies only when they fit on one line.

---

## 9. Testing

Non-trivial logic leaves one runnable check behind. The smallest thing that fails if the logic breaks.
No coverage mandate; the requirement is that a regression has a test that can fail.

Cross-language parity: the same detection logic lives in Python and Kotlin. Each copied piece either
has a parity test (`ParityTest`, `MlConstantsTest`, `test_system_prompt_matches_kotlin`,
`SmsTokenizerTest`) or a shared source of truth (`sentinel/data/rules.json`, trusted domains asset).
A pair with no tie is a gap — see `docs/ARCHITECTURE_RULES.md`.

---

## 10. Pre-commit hook (opt-in)

A fast pre-commit hook lives at `.githooks/pre-commit`. It runs the Python tests (the parity fixture
staleness is covered by `tests/test_rules_parity.py::test_parity_fixture_is_up_to_date`) and refuses the
commit on failure. It does **not** run the Android half (JDK may not be present on every machine).

To enable it (do not run this command yourself — each engineer opts in):

```
git config core.hooksPath .githooks
```

To stop using it:

```
git config --unset core.hooksPath
```

The hook is opt-in until a linter is installed; review is the real enforcement until then. A hook can
be bypassed with `--no-verify`, so a bad commit is still caught in review.
