Galaxy F14, APK from bf5ed83 (audit round 3 fixes), 2026-11-07, battery, adb over Wi-Fi. Two cold opens via a share
intent with an SBI blocked-account scam that asks the user to share an OTP. Both: no crash, HIGH RISK / SCAM, SMS model
scam 1.00, prompt_path=prefix_cache, TTFT 1714 and 1586 ms. Advice kept the negated line (do not share the OTP with
anyone) and contained no instruction to share a secret (after_run2.png). integrity_cache.json now carries
last_verified_ms for every model after the first start (weekly re-hash, BAT-3).
