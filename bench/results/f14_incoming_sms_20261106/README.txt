Galaxy F14 incoming-SMS test, 2026-11-06 18:53 (real SMS from another phone, Vi network).
Sent: Hinglish electricity cut-off scam, UPI collect + PIN scam, loan APK scam with link (each arrived twice).
Not delivered: SBI KYC message with a link and the HDFC OTP message (the sender's carrier refused them).
Result: 6 SMS received, 6 PS3 Sentinel notifications, all "Possible scam from <sender> / Risk: HIGH",
no SMS text in the notification (f14_notification_shade.png).
Tapping the newest alert opened the app with the UPI message: HIGH RISK, SCAM 1.00, cues highlighted,
Llama advice on the prefix_cache path (f14_from_notification.png). PS3Bench: prompt_tokens=117,
ttft_ms=11181, decode 10.3 tok/s; UI: detect 451.0 ms (SMS 436.5). This first analysis after the app
had been in the background was slow compared with the warm path (TTFT 3.5-4.1 s, detect 25-55 ms).
Note: before this test the phone was still in airplane mode, left on by deploy/android/full_test.ps1.
Not tested: a legitimate SMS (false-positive side) arriving through the receiver.
