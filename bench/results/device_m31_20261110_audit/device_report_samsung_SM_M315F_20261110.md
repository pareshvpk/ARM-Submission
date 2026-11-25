# Device test: samsung SM-M315F (2026-11-10)

Device: samsung SM-M315F (Exynos 9611), 5.4 GiB RAM (MemTotal 5706212 kB), Android 12 (API 31).
CPU features: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid. Free space on /sdcard: /dev/fuse       112G  73G   38G  66% /storage/emulated.
Serial <adb-serial>, APK android/app/build/outputs/apk/debug/app-debug.apk, test at 20261110_193159. Install: Success.

Scope rule: only `org.ps3.sentinel` was installed, launched, granted permissions and read; no phone setting, other app or
file was changed. Messages went in through the app's share intent; UI text was read with `uiautomator dump /dev/tty`
and screenshots were saved with `exec-out screencap` without writing files on the phone. At the end the app was
uninstalled with `--user 0` and the leftover checks below ran without dismissing anything else.

## Results

| Measure | Value |
|---|---|
| Install (`adb install --user 0`) | Success |
| Permissions | RECEIVE_SMS granted; POST_NOTIFICATIONS skipped on API 31 (< 33) |
| Cold start (`am start -W` TotalTime) | 1.97 s |
| Cold launch after model push: integrity check | url 65 ms, sms 1767 ms, llama 17396 ms |
| Model load | url 56 ms, sms 11474 ms, llama 336 ms |
| Memory with all models loaded | TOTAL PSS 1583487 kB, TOTAL RSS 1657395 kB, swap PSS 275 kB, MemAvailable 1935412 kB |
| Free space on /sdcard | /dev/fuse       112G  73G   38G  66% /storage/emulated |
| Leftover checks after uninstall | all absent |

## Messages

| # | Message | Verdict | Risk | Detect (SMS) | Llama TTFT | Decode | Advice | Advice source |
|---|---|---|---|---|---|---|---|---|
| 1 | SBI KYC | not read | not read | not read | none | none | not read | not read |
| 2 | Hinglish Axis card KYC | not read | not read | not read | none | none | not read | not read |
| 3 | Hinglish UPI refund PIN | not read | not read | not read | none | none | not read | not read |
| 4 | Instant loan .apk link | not read | not read | not read | none | none | not read | not read |
| 5 | Shoe-store promotion | not read | not read | not read | none | none | not read | not read |
| 6 | Order delivered | not read | not read | not read | none | none | not read | not read |

## Findings

- Messages analysed: 0 of 6.
- Did not finish within 180s: message(s) 1, 2, 3, 4, 5, 6.
- Leftover checks after uninstall: all absent.
- Permissions: RECEIVE_SMS granted; POST_NOTIFICATIONS skipped on API 31 (< 33).
- No phone setting was changed, logcat was not cleared, and no file was written on the phone outside `/sdcard/Android/data/org.ps3.sentinel`.

