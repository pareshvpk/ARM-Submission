# Device test: samsung SM-M315F (2026-11-24)

Device: samsung SM-M315F (Exynos 9611), 5.4 GiB RAM (MemTotal 5706212 kB), Android 12 (API 31).
CPU features: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid. Free space on /sdcard: /dev/fuse       112G  76G   35G  69% /storage/emulated.
Serial <adb-serial>, APK android\app\build\outputs\apk\release\app-release.apk, test at 20261124_181653. Install: Success.

Scope rule: only `org.ps3.sentinel` was installed, launched, granted permissions and read; no phone setting, other app or
file was changed. Messages went in through the app's share intent; UI text was read with `uiautomator dump` to
`/data/local/tmp/ps3_ui.xml` and `cat`, and that file was deleted right after every read. Screenshots were saved
with `exec-out screencap` without writing files on the phone. At the end the app was
uninstalled with `--user 0` and the leftover checks below ran without dismissing anything else.

## Results

| Measure | Value |
|---|---|
| Install (`adb install --user 0`) | Success |
| Permissions | RECEIVE_SMS granted; POST_NOTIFICATIONS skipped on API 31 (< 33) |
| Cold start (`am start -W` TotalTime) | 0.76 s |
| Cold launch after model push: integrity check | url 29 ms, sms 1046 ms, llama 13282 ms |
| Model load | url 17 ms, sms 6645 ms, llama 404 ms |
| Memory with all models loaded | TOTAL PSS 1528304 kB, TOTAL RSS 1619751 kB, swap PSS 390 kB, MemAvailable 2466888 kB |
| Free space on /sdcard | /dev/fuse       112G  76G   35G  69% /storage/emulated |
| Leftover checks after uninstall | all absent |

## Messages

| # | Message | Verdict | Risk | Detect (SMS) | Llama TTFT | Decode | Advice | Advice source |
|---|---|---|---|---|---|---|---|---|
| 1 | SBI KYC | HIGH RISK, scam | 0.90 | 478.2 ms (441.1) | 6869 ms | 4.7 tok/s | 41406.0 ms | Llama 3.2 1B (On-Device) |
| 2 | Hinglish Axis card KYC | HIGH RISK, scam | 0.90 | 190.7 ms (177.2) | 7160 ms | 4.8 tok/s | 26213.5 ms | Llama 3.2 1B (On-Device) |
| 3 | Hinglish UPI refund PIN | HIGH RISK, scam | 0.89 | 176.2 ms (165.2) | 7604 ms | 5.4 tok/s | 27151.3 ms | Llama 3.2 1B (On-Device) |
| 4 | Instant loan .apk link | HIGH RISK, scam | 0.90 | 193.0 ms (180.9) | 6416 ms | 5.7 tok/s | 24370.2 ms | Llama 3.2 1B (On-Device) |
| 5 | Shoe-store promotion | HIGH RISK, scam | 0.83 | 180.0 ms (171.4) | 5516 ms | 5.6 tok/s | 23116.7 ms | Llama 3.2 1B (On-Device) |
| 6 | Order delivered | LOOKS SAFE, ham | 0.10 | 107.3 ms (102.0) | none | none | 0.1 ms | Heuristic Template |

## Findings

- Messages analysed: 6 of 6.
- Leftover checks after uninstall: all absent.
- Permissions: RECEIVE_SMS granted; POST_NOTIFICATIONS skipped on API 31 (< 33).
- No phone setting was changed, logcat was not cleared, and no file was left on the phone: the only file written outside `/sdcard/Android/data/org.ps3.sentinel` is the UI dump `/data/local/tmp/ps3_ui.xml`, which was deleted right after each read.

