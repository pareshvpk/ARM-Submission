# Phase 1 betterment: what was done

## 1. Sensitive-message pre-filter

- **Status**: Done
- **Evidence**:
  - Implementation: `sentinel/routine_filter.py`, `android/app/src/main/java/org/ps3/sentinel/core/RoutineFilter.kt` (already existed).
  - Regression tests: `tests/test_routine_filter.py`, `android/app/src/test/java/org/ps3/sentinel/core/RoutineFilterTest.kt`.
  - Behavior: Regression tests prove that six suspicious registered-sender messages still reach the detector:
    1. OTP share request
    2. Prize offer
    3. Refund plus UPI PIN
    4. eSIM activation
    5. KYC block
    6. Debit with callback number
  - A plain debit alert is skipped.
  - Earlier measurement on real inboxes is documented in `docs/benchmarks.md`.

## 2. Incoming MMS text scanning

- **Status**: Done, not device-tested
- **Evidence**:
  - Implementation: `android/app/src/main/java/org/ps3/sentinel/sms/IncomingMmsReceiver.kt`, `MmsWatcher.kt`, `MmsWatchJobService.kt`, `MmsScanner.kt`, and helpers.
  - Attribution: Adapted from pareshvpk/Phase under MIT (see `NOTICE`).
  - Permissions: New permissions `RECEIVE_MMS` and `READ_SMS`.
  - First-run logic: Stores the newest MMS ID and reads nothing older.
  - Pipeline integration: Extracted text passes through the exact same SMS pipeline.
  - JVM tests: `android/app/src/test/java/org/ps3/sentinel/sms/Mms*Test.kt`.
  - Device test with a real MMS: TO BE FILLED.

## 3. App-access review

- **Status**: Done
- **Evidence**:
  - Implementation: `android/app/src/main/java/org/ps3/sentinel/core/AppAccessReview.kt` (added 2026-11-22), surfaced on the Protection tab (`ui/ProtectionActivity.kt`, `res/layout/activity_protection.xml`).
  - Presentation: Wording states facts about access (such as Accessibility screen reading, gesture permissions, and SMS access), not that an app is malicious.

## 4. Scoped accessibility feature: Check this screen

- **Status**: Done
- **Evidence**:
  - Implementation: `android/app/src/main/java/org/ps3/sentinel/a11y/ScreenCheckService.kt`.
  - Configuration: Off by default. Reads the active window only when the user explicitly taps the accessibility button.
  - Security & privacy boundaries: Skips password fields and Sentinel's own application window. Caps inspection at 2000 characters. Nothing is stored or sent anywhere off-device.
  - Hand-off: Opens the normal Check screen with the inspected text. Core SMS scanning works without it.

## 5. Two-sentence advice

- **Status**: Done
- **Evidence**:
  - Token and latency measurements: On 20 stored English Llama outputs, the median answer is 73 tokens. Two sentences need about 42 tokens vs 65 for three and 71 at the old stop of four. This saves about 5 s decode time on the Galaxy M31 at 5.6 tok/s.
  - Implementation: Python (`sentinel/advisor.py`) and Kotlin (`android/app/src/main/java/org/ps3/sentinel/core/Advisor.kt`) both cap advice at two sentences plus the fixed steps.
  - Fixtures: Test fixtures regenerated to reflect the two-sentence constraint.

## 6. Submission packaging script

- **Status**: Done
- **Evidence**:
  - Implementation: `scripts/package_submission.py` (added 2026-11-22).
  - Verification: `tests/test_package_submission.py`.

## 7. UI: Five-tab layout & alert log

- **Status**: Done
- **Evidence**:
  - Layout: Five-tab layout (Home, Alerts, Check, Protection, Settings) with a floating bottom glass bar.
  - Privacy: Alert log retains timestamp, risk level, label, and sender only; never message text. Capped at at most 50 entries.

## 8. Architectural decisions: Repo A vs Repo B

- **Status**: Evaluated
- **Evidence**:
  - Kept from Repo A: Multilingual MiniLM SMS model, character-level URL CNN, fusion and scam rules, zero internet permissions (`android.permission.INTERNET` omitted), model integrity verification against APK hashes, and Arm hardware capability checks.
  - Not taken from Repo B: Internet permission, TF-IDF classifiers, network IDS.

## 9. Acceptance gate

- **Status**: Done
- **Evidence**:
  - Automated test suite: `scripts/check.ps1` passes (531 pytest tests and Android unit tests).
  - Manual verification: Five tabs checked on a Samsung Galaxy M31.
