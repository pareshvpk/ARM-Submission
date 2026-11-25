# PS3 Sentinel engineering report

PS3 Sentinel is an offline SMS scam and phishing assistant. Its Android app and Python Linux CLI run the same detection pipeline: collect a message, analyze SMS cues and links, explain the verdict, and recommend safe next steps. The Android manifest has no `INTERNET` permission.

## System design

The pipeline combines three signals:

1. Regex cues detect urgency, threats, identity checks, credential requests, payment requests, and app installation requests.
2. A multilingual SMS model classifies ham, unwanted promotions, and scams. A character CNN scores extracted URLs.
3. Fusion combines the scores into a 0–1 risk score, a low/medium/high level, cue spans, and per-link verdicts. Llama 3.2 1B provides guarded advice only for medium- or high-risk messages; lower-risk messages use templates.

The rules in `sentinel/data/rules.json` are shared by Python and Kotlin and checked by parity fixtures. The Python command line accepts a message, stdin, or a batch file. Android checks incoming SMS, pasted text, and shared messages.

## Models and runtime

- SMS: multilingual MiniLM-L12, fine-tuned for three classes and exported to ExecuTorch. The shipped int8 model is about 51 MB; a hybrid 112 MB model is available for phones without dot-product support.
- URL: 284k-parameter character CNN, about 1.1 MB in fp32 ExecuTorch format.
- Advice: Llama 3.2 1B Instruct, SpinQuant INT4 with 8-bit dynamic activations, about 1.14 GB.

Android uses ExecuTorch 1.5.1 with XNNPACK. The local Armv8.0 AAR supports older Armv8.0 phones; CPU features select the NEON or dot-product model path. Llama output passes an advice guard that removes unsafe instructions and falls back to templates when needed.

## Android device coverage

The app was checked on Galaxy M31, Galaxy F12, moto g73 5G, Galaxy M32, and Galaxy F14 5G. Devices without dot-product support use the hybrid SMS model; supported devices use int8. The release check and per-device results are recorded under `docs/device_tests/`.

Observed warm SMS detection ranges from 13 ms to about 10.4 s across devices; the first message after launch accounts for the largest values on slower phones. Llama time to first token ranges from about 1.2 s on the Galaxy F14 to 12.6 s on the Galaxy F12. Phone performance depends on device speed and temperature; see the device reports for test conditions.

## Detection quality

Held-out evaluation is independent of device hardware. The SMS v5 model scored macro F1 0.977 on a 62,176-message template-grouped set and 0.870 on a 631-message Indian-real subset. URL v2 scored precision 0.975, recall 0.741, and F1 0.842 on 658k URLs. Shipped-rule evaluation reports strong English and Hinglish results, with weaker cells in some native-script subsets; detailed tables and caveats are in `docs/benchmarks.md`.

## Privacy and limits

SMS text and URLs are processed locally. Android logs truncated hashes and timings rather than message contents. Alert text is encrypted with an Android Keystore key and can be cleared in the app. The optional accessibility screen check is off by default and reads the active window only after the user taps its control.

A rooted-device packet capture was not available for Android; offline operation is supported by the manifest permissions and an airplane-mode run. Native-script detection and user-effectiveness studies remain areas for improvement.
