# PS3 Sentinel - On-Device Scam SMS and Phishing Link Assistant (Android)

Android application for Problem Statement 3 (PS3), Bharat AI-SoC Challenge 2026-27.
Package: `org.ps3.sentinel`
App Name: `PS3 Sentinel`

PS3 Sentinel runs entirely on-device, fully offline, combining local heuristic cue extraction, an ExecuTorch-based character CNN URL classifier, risk fusion, and an on-device Llama 3.2 1B Instruct model to deliver instant scam verdicts and safe remediation advice.

---

## Architecture Summary

- **Pure Core Logic (`org.ps3.sentinel.core`)**: Zero Android dependencies; contains URL normalisation/extraction, SMS cue matching (including Hinglish threats), URL indicator heuristics, risk fusion engine (combo rule 0.72), Llama 3 prompt construction, guardrail sanitiser, and character vocab encoder. Fully unit-tested on JVM.
- **Machine Learning Layer (`org.ps3.sentinel.ml`)**:
  - `ModelStore`: Discovers and validates models in external app storage.
  - `UrlClassifier`: Runs `url_cnn_v2.pte` character CNN via ExecuTorch Android AAR (`org.pytorch:executorch-android:1.5.1`).
  - `LlamaAdvisor`: Runs Llama 3.2 1B Instruct via ExecuTorch `LlmModule` with token streaming and PyTorchObserver latency parsing.
- **Pipeline (`org.ps3.sentinel.Pipeline`)**: Orchestrates URL extraction, URL classification, SMS cue parsing, risk fusion, and Llama advice (invoked only for medium and high risk). Includes a no-LLM `analyseFast()` path for incoming SMS processing.
- **UI & System Integration (`org.ps3.sentinel.ui`, `org.ps3.sentinel.sms`)**:
  - `MainActivity`: Material Design interface with risk badges, highlighted cue spans (`SpannableString`), plain-text unclickable links (FR-09 compliant), streaming advice, latency breakdown, and model status line.
  - Share Target: Handles `android.intent.action.SEND` (`text/plain`) to inspect shared messages.
  - `SmsReceiver`: Receives incoming SMS via `android.provider.Telephony.SMS_RECEIVED`, reconstructs multipart messages, runs `analyseFast()`, and posts high-priority notifications for medium/high risk threats. Tapping the notification launches `MainActivity` to generate full Llama advisory.

---

## Build Setup

Requirements:
- Android SDK 35 (compileSdk 35, targetSdk 35, minSdk 26)
- Java 17 / Kotlin 2.0.21
- Android Gradle Plugin 8.7.3
- Target ABI: `arm64-v8a` only

### Building the APK

From the `android/` directory:

```bash
./gradlew assembleDebug
```

On Windows:

```cmd
gradlew.bat assembleDebug
```

The resulting APK is generated at:
`android/app/build/outputs/apk/debug/app-debug.apk`

### Release signing

The `release` build type keeps `isMinifyEnabled=false` (ExecuTorch JNI requires
shrinking off) and sets `isDebuggable=false` explicitly. No signing key is
committed: `release` is unsigned unless signing material is supplied via
environment variables or a gitignored `keystore.properties` file.

With environment variables (e.g. in CI):

- `RELEASE_STORE_FILE` — path to the keystore file
- `RELEASE_STORE_PASSWORD` — keystore password
- `RELEASE_KEY_ALIAS` — key alias
- `RELEASE_KEY_PASSWORD` — key password

Or create `android/keystore.properties` (gitignored) with:

```properties
storeFile=/path/to/release.keystore
storePassword=...
keyAlias=...
keyPassword=...
```

Then:

```bash
./gradlew assembleRelease
```

When all four values are present, Gradle signs the release APK/AAB with them.
When absent, `release` builds unsigned and only `assembleDebug` is used for
local testing; never distribute a debug APK.

---

## Device Installation

Install the debug APK for the primary user only. On phones with a work profile
or Secure Folder, a plain `adb install` targets every user; `--user 0` keeps
those profiles untouched (DT-12):

```bash
adb install --user 0 -r android/app/build/outputs/apk/debug/app-debug.apk
```

---

## Pushing Models to Device

In accordance with NFR-05 and APK size constraints, model weights are not packaged inside the APK. They are stored in external files directory at:
`/sdcard/Android/data/org.ps3.sentinel/files/models/`

### Launch once before pushing (DT-1)

Launch the app once and stop it before any folder is created on the phone. The
app must create `/sdcard/Android/data/org.ps3.sentinel` itself: on Android 14
(for example the moto g73 5G) a folder created first by adb is not readable by
the app, and the app then reports every model missing. Wait 3 s after the
launch, force-stop the package with `--user 0`, and only then create the models
folder and push the files.

```bash
# 1. Let the app create its own external files folder, then stop it.
adb shell am start --user 0 -W -n org.ps3.sentinel/.ui.MainActivity
sleep 3
adb shell am force-stop --user 0 org.ps3.sentinel

# 2. Only now create the target directory.
adb shell "mkdir -p /sdcard/Android/data/org.ps3.sentinel/files/models"

# 3. Push URL Classifier model and vocabulary
adb push models/url_v2/url_cnn_v2.pte /sdcard/Android/data/org.ps3.sentinel/files/models/
adb push models/url_v2/vocab.json /sdcard/Android/data/org.ps3.sentinel/files/models/

# 4. Push SMS model, id map and vocabulary
adb push models/sms_v6ml/sms_int8.pte /sdcard/Android/data/org.ps3.sentinel/files/models/
adb push models/sms_v6ml/id_map.json /sdcard/Android/data/org.ps3.sentinel/files/models/
adb push models/sms_v6ml/sms_vocab.txt /sdcard/Android/data/org.ps3.sentinel/files/models/

# 5. Phones WITHOUT dot product only: push the hybrid fp32 SMS model as sms_fp32.pte.
#    sms_int8.pte is not needed on such phones.
#    Check the Features line first: no asimddp means the app needs sms_fp32.pte.
adb shell grep Features /proc/cpuinfo
#    Run this push only when the line above has no asimddp:
adb push models/sms_v6ml/sms_fp32_int8emb.pte /sdcard/Android/data/org.ps3.sentinel/files/models/sms_fp32.pte

# 6. Push Llama 3.2 1B Instruct model and tokenizer (phone names from model_files.json)
adb push models/llama32_et_community/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte /sdcard/Android/data/org.ps3.sentinel/files/models/llama.pte
adb push models/llama32_et_community/tokenizer.model /sdcard/Android/data/org.ps3.sentinel/files/models/tokenizer.model
```

Step 5 applies only to phones whose `/proc/cpuinfo` Features line lacks the `asimddp` flag, for example the Galaxy M31. Push `models/sms_v6ml/sms_fp32_int8emb.pte` as `sms_fp32.pte`; `sms_int8.pte` is not needed on such phones (`ModelStore.smsModelFileFor` loads only the fp32 file there). On a phone with dot product the app loads `sms_int8.pte` and never opens `sms_fp32.pte`, so pushing `sms_fp32.pte` is skipped there. `deploy/android/device_test.ps1` and `deploy/android/full_test.ps1` already do this automatically: they read the Features line over adb, push `sms_fp32.pte` only when dot product is absent (and skip `sms_int8.pte`), fall back to pushing `sms_int8.pte` if `sms_fp32.pte` is not present locally, and remove a leftover copy on dot-product phones.

### Generating the integrity manifest

Before pushing the models, generate `models.sha256` in the models folder so the app can verify file integrity on load:

```bash
python deploy/android/write_models_manifest.py /path/to/models
```

Push the manifest together with the models:

```bash
adb push /path/to/models/models.sha256 /sdcard/Android/data/org.ps3.sentinel/files/models/
```

### Verifying the pushed files

Compare the SHA-256 that `sha256sum` reports on the phone with the local hash of
the same file:

```bash
adb shell sha256sum /sdcard/Android/data/org.ps3.sentinel/files/models/url_cnn_v2.pte
# PowerShell:
Get-FileHash models/url_v2/url_cnn_v2.pte -Algorithm SHA256
```

`deploy/android/full_test.ps1` and `deploy/android/device_test.ps1` do this for
every pushed model file, for `models.sha256`, and for `sms_fp32.pte` when it is
present locally, and stop on a mismatch.

Verify models on device:

```bash
adb shell "ls -lh /sdcard/Android/data/org.ps3.sentinel/files/models"
```

Expected files:
- `url_cnn_v2.pte` (~1.4 MB)
- `vocab.json` (~2 KB)
- `sms_int8.pte` (int8 SMS model)
- `id_map.json`
- `sms_vocab.txt`
- `llama.pte` (~1.2 GB, SpinQuant INT4 / EO8)
- `tokenizer.model` (~4.3 MB)
- `sms_fp32.pte` (optional; used on phones without dot product)

If the Llama model is not pushed, the app seamlessly falls back to the deterministic indicator-based template advice. If the URL model is not pushed, heuristic indicators are used.

### Load order and the integrity cache

On every start the app loads rules, then the URL model, then the SMS model. Llama verify, load and prefix prefill wait until the SMS model is ready and either the UI is opened or no SMS analysis is waiting, so a process started for an SMS broadcast posts the alert without competing with the 1.1 GB Llama hash or prefill on the little-core cpuset. The receiver waits at most 3 s for the SMS model, then decides with rules plus the URL model and updates the same notification id once the full result is ready (`PS3Timing sms_received_to_alert_ms`).

After a full SHA-256 check passes, the app records name, size, last-modified time and hash in `integrity_cache.json` inside `noBackupFilesDir`. Every cold process start re-hashes each model before its first load; the file is bookkeeping only and never skips that first hash. Inside one process, the per-process verification cache is the fast path: repeat checks return the first result without re-hashing, unless the file's size or last-modified time changed, which invalidates the cached entry.

---

## Permissions

1. `android.permission.RECEIVE_SMS`: Requested at runtime. Required for `SmsReceiver` to inspect incoming SMS messages automatically.
2. `android.permission.POST_NOTIFICATIONS`: Requested at runtime on Android 13+ (API 33+). Required to alert users when a scam SMS is detected in the background. The deploy scripts grant it only when `getprop ro.build.version.sdk` reports 33 or higher; below API 33 the permission does not exist and no runtime grant is needed (DT-10).

*Note*: No internet permission (`android.permission.INTERNET`) is declared or requested. The app is structurally unable to transmit network traffic.

---

## Offline and Privacy Guarantees

- **FR-09 Compliance**: No URL is ever opened, fetched, or resolved. Links in the UI are rendered as non-clickable plain text (`autoLink="none"`, `linksClickable="false"`).
- **NFR-06 Compliance**: All inference (URL CNN, heuristics, fusion, Llama 3.2) executes 100% locally on the device CPU/NPU with ExecuTorch.
- **NFR-07 Compliance**: Zero analytics SDKs, zero telemetry, zero egress. Private SMS contents never leave memory.

### Pending messages after process death

Pending notification messages are kept in the app-private no-backup files directory (`Context.noBackupFilesDir`), each body encrypted with AES-256-GCM under the Android Keystore key `ps3_pending_sms` (alias created on first use and never exported), so only the app can read them and they are excluded from device transfers. At most 20 entries are kept and entries older than 24 hours are deleted on every read and write, bounding the exposure window. A message is stored before analysis so a process death during analysis does not lose it; it is deleted when analysis finds no alert for it, and the entry is marked done after an alert is posted.

---

## Running JVM Unit Tests

The core pure-logic unit tests can be executed on JVM without Android dependencies or emulators:

```bash
./gradlew test
```

Test classes:
- `org.ps3.sentinel.core.UrlFeaturesTest`
- `org.ps3.sentinel.core.CuesTest`
- `org.ps3.sentinel.core.UrlIndicatorsTest`
- `org.ps3.sentinel.core.FusionTest`
- `org.ps3.sentinel.core.AdvisorTest`
- `org.ps3.sentinel.core.PromptSplitTest`
- `org.ps3.sentinel.core.UrlEncoderTest`

---

## Prefix KV-cache (ON by default)

Reading the whole prompt on every message costs about 4.7 s of prefill before the first
token on the Galaxy F14 (roughly 250 prompt tokens at about 55 tok/s). The fixed system
prefix is identical for every message, so it can be prefilled once into the Llama KV cache
and each message can then generate from its per-message tail only. This is proposals P0,
P1, and P7 in `docs/research/2026-11-06_performance.md`, prepared on Android behind a
flag. It is ON by default on the phone since the 2026-11-06 owner decision:
`bench/results/f14_prefix_20261106_151141/summary.txt` measured TTFT p50 5548 ms to
4280 ms and prompt tokens 312 to 127, advice identical forward vs reversed 12 of 12 in
both modes (no message affects another), byte-identical to the full-prompt path on 5 of
12 (prefilling in two chunks changes floating-point rounding), and the owner accepted that
difference.

### How to turn it off

The default is `true` in code:

```kotlin
const val USE_PREFIX_CACHE: Boolean = true
```

Create the runtime flag file `prefix_cache.off` in the models folder
(`/sdcard/Android/data/org.ps3.sentinel/files/models/` — the folder `ModelStore` uses)
to disable the prefix path without a rebuild (it wins over the constant):

```bash
adb shell touch /sdcard/Android/data/org.ps3.sentinel/files/models/prefix_cache.off
adb shell am force-stop --user 0 org.ps3.sentinel
```

`LlamaAdvisor` checks the file once when it is created (the decision is passed in
from `SentinelApp` via the models dir) and logs once at creation in `PS3Sms`:
`prefix cache enabled` or `prefix cache disabled`, with the reason (constant or
flag file). Remove the file to go back to `prefix_cache`:

```bash
adb shell rm -f /sdcard/Android/data/org.ps3.sentinel/files/models/prefix_cache.off
```

The `prefix_cache.on` file still enables the prefix path (it simply matches the
default now); `prefix_cache.off` wins when both files exist. Changing the
constant to `false` also works but needs a rebuild and reinstall.
When enabled, `LlamaAdvisor` prefills `FIXED_PROMPT_PREFIX`
(from `core/Advisor.kt`) on a background thread at warm-up, generates each message from
its tail only, and after each answer runs `resetContext()` plus `prefillPrompt(prefix)`
on the background thread while the user reads the result. All calls into the module are
serialized by one lock, and a message that arrives while a prefill is still running waits
up to `PREFIX_PREFILL_WAIT_TIMEOUT_MS` (5000 ms) before falling back to the old
full-prompt path with a `resetContext()` first. Any native failure disables the prefix
path for that `LlamaAdvisor` instance, logs a warning, and falls back to the full-prompt
path, so a failure never blocks advice. To revert the default, set the constant back to
`false` and rebuild; the prompt text itself is unchanged.

The path used is recorded in `LlamaStats.promptPath` (`prefix_cache` or `full_prompt`)
and in logcat as `prompt_path=<path>` (tags `PS3Sms` and `PS3Llama`) so the bench can
compare the two paths. After each advice finishes, `LlamaAdvisor` also logs one line
with tag `PS3Bench`:
`prompt_path=<prefix_cache|full_prompt> prompt_tokens=<n> ttft_ms=<n> decode_tok_s=<x>
advice_sha8=<first 8 hex of sha256 of the final advice text>`.
Neither SMS text nor advice text is logged, only the hash.

### Three checks to run on the phone

Run on a real phone (e.g. Galaxy F14), cool device, same model files, and same
messages in both runs, with temperature fixed at 0.0. The script
`deploy/android/prefix_cache_check.ps1` automates this: it reads the first
`-Count` (default 20) non-empty lines of `bench/llm_prompts.txt`, runs off then on
through the share intent, and writes
`bench/results/f14_prefix_<yyyyMMdd_HHmmss>/runs.csv` plus `summary.txt`
(count per mode, TTFT p50/p95 per mode, mean `prompt_tokens` per mode, identical
advice count, and PASS/FAIL for the three checks). It always removes both
`prefix_cache.on` and `prefix_cache.off`:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/android/prefix_cache_check.ps1 -Serial <serial>
```

The script needs `PS3_ADB_SERIAL` set (or `-Serial`), uses
`%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` by default
(or `-Adb`), and waits up to `-TimeoutSec` (default 90) per message for the next
`PS3Bench` line.

1. **Advice identical**: Run 20 messages (e.g. the guard corpus) with `prefix_cache.off`
   present and record the advice text for each message. Remove `prefix_cache.off`,
   rerun the same 20 messages, and compare byte for byte. The advice must be identical
   on all 20.
2. **Prompt tokens equal the tail length**: In logcat (`PS3Llama` stats) and
   `prompt_path` lines, `prompt_tokens` with the cache on must equal the tail length
   (the text from `Message:` onward), not the full prompt length, and must be smaller
   than the `prompt_tokens` recorded with the cache off by the fixed prefix length.
3. **First-token time before and after**: Record TTFT (shown in the UI and in the stats
   `ttft_ms`) with the cache off and then on on the same 20 messages. Report
   p50/p95 before and after; research estimates about 4.7 s to about 1.8 s on the F14,
   but the measured numbers are what count.
