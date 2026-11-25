# Release build device checks, 2026-11-22

Date: 2026-11-22

APK: `android/app/build/outputs/apk/release/app-release.apk` (signer `34014541...fb3b`, same as published release).
Installation: Release build was installed on each phone. Models were pushed to device storage and SHA-256 checked against the release `SHA256SUMS`.

## Method

Messages were shared into the app with the Android share intent, since the release build has no test SMS receiver. The app language was switched with the per-app locale.

### Test messages

- English scam: Dear customer your SBI account will be blocked today. Update KYC now at http://sbi-kyc-update.in/verify or call 9876543210
- Tamil scam: the same message in Tamil (உங்கள் SBI கணக்கு இன்று முடக்கப்படும். உடனே KYC புதுப்பிக்கவும் ... அல்லது 9876543210 அழைக்கவும்)
- Hindi scam: the same message in Hindi (आपका SBI खाता आज बंद हो जाएगा। तुरंत KYC अपडेट करें ... या 9876543210 पर कॉल करें)
- Safe: Your OTP for login is 482913. Do not share it with anyone. -HDFC Bank

## Phone results

| Device | Android | SoC / CPU features | Tier | SMS model | Model loads (url / sms / llama, integrity in brackets) | English scam | Tamil scam | Hindi scam | Safe OTP | Detect ms | Llama advice | PSS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Samsung M31 SM-M315F | 12 | Exynos 9611, no asimddp | LIGHT | sms_fp32 | 15 / 6802 / 428 ms (21 / 969 / 14042) | HIGH 0.90 | not run | not run | SAFE 0.12 (Hi Amma safe message; OTP message not run) | 956-1476 | timeout at 56.5 s, template advice shown | 1.44 GB peak (debug build, earlier today) |
| Galaxy F14 5G SM-E146B | 15 | s5e8535 (Exynos 1330), atomics asimddp fphp | FULL | sms_int8 | 19 / 292 / 176 ms (22 / 153 / 5316) | HIGH RISK 0.90 | HIGH RISK 0.90, Tamil UI + Tamil template advice | HIGH RISK 0.90, Hindi UI + Hindi template advice | LOOKS SAFE 0.30 | 138-176 | EN: TTFT 1881 ms, 10.2 tok/s, total 9.1 s | 1.37 GB |
| Samsung M32 SM-M325F | 13 | MT6769V (Helio G80), atomics asimddp fphp | FULL | sms_int8 | 81 / 7892 / 596 ms (197 / 1909 / 29660) | HIGH RISK 0.90 | HIGH RISK 0.90, Tamil UI + Tamil template advice | HIGH RISK 0.90, Hindi UI + Hindi template advice | LOOKS SAFE 0.30 | 241-354 | EN: TTFT 3728 ms, 6.4 tok/s, advice 14.9 s | 1.39 GB |
| moto g73 5G | 14 | MT6855V (Dimensity 930), atomics asimddp fphp | FULL | sms_int8 | 12 / 3584 / 152 ms (20 / 311 / 4754) | HIGH RISK 0.90 | 0.90, Tamil UI | HIGH RISK 0.90, Hindi UI | LOOKS SAFE 0.30 | 88 (safe msg) | EN: TTFT 1599 ms, 9.9 tok/s | 1.44 GB |
| Samsung F12 SM-F127G | 13 | Exynos 850, atomics fphp, no asimddp, 4 GB | LIGHT | sms_fp32 | 37 / 10567 / 646 ms (94 / 2925 / 45937) | HIGH RISK 0.77 (URL prob 0.85, others 1.00) | HIGH RISK 0.77, Tamil UI | HIGH RISK 0.77, Hindi UI + Hindi template | LOOKS SAFE 0.30 | 10031 when Llama prefill running (10 s gate timeout, falls back) | EN: TTFT 14.5 s, 4.0 tok/s | 1.35 GB |

M31 note: Android 12 per docs/device_tests/galaxy_m31_20261108.md. Release build message checks were run on 2026-11-22 evening. Hi Amma safe message gave SAFE, risk 0.12, detect 956 ms. SBI KYC link scam gave HIGH, risk 0.90, detect 1476 ms. Llama advice hit the timeout at 56.5 s and the template advice was shown. A meeting message sent through the text-selection action gave SAFE, risk 0.09.

## Findings

1. The Galaxy F14 5G, M32, moto g73 and F12 gave the right verdict in all four checks on the release build. The M31 message checks were run on the release build on 2026-11-22 evening. Hi Amma safe message gave SAFE, risk 0.12, detect 956 ms. SBI KYC link scam gave HIGH, risk 0.90, detect 1476 ms; Llama advice hit the timeout at 56.5 s and the template advice was shown. A meeting message sent through the text-selection action gave SAFE, risk 0.09.
2. On the Galaxy F12 (no dot product, 4 GB) a message checked while Llama is still warming up after launch waits up to 10 s for the SMS model and then falls back; the verdict stays correct. The URL model scored the test phishing link 0.85 on the F12 against 1.00 on dot-product phones (same model file).
3. Not tested: a real incoming SMS on the release build, and the Android 13+ notification denial dialog (every phone already had notifications allowed).
4. Raw screenshot files in `tmp_work/device_checks_2026-11-22/` (`e146_*.png`) are not committed. Committed release screenshots from this check are in `docs/screenshots/2026-11-22_f14/`.
