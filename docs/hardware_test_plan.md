# Android device test plan

Use the Android scripts to install, exercise, and collect evidence from a connected phone. The scripts preserve the phone's user profile and restore airplane mode in their cleanup path.

## Release check

From PowerShell, connect one phone with USB debugging enabled and run:

```powershell
deploy/android/full_test.ps1 -Serial <serial>
```

The script installs the APK, pushes the model files, verifies their hashes, grants notification access when needed, and runs five sample messages in airplane mode. It saves screenshots, short screen recordings, logcat timings, and memory information under `bench/results/`.

## Per-device report

For a concise compatibility report, run:

```powershell
deploy/android/device_test.ps1 -Serial <serial>
```

This records the phone model, Android version, CPU features, available storage, model load, message results, and memory use. Per-phone reports are stored under `docs/device_tests/`.

## Evidence limits

The manifest declares no `INTERNET` permission, and the offline scenario checks that analysis still works in airplane mode. A packet capture on Android has not been performed because the test phones are not rooted. See `docs/privacy_proof.md` for the privacy evidence and limits.
