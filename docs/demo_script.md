# Android demo video script

Target length: 3–4 minutes. Show one complete local analysis and explain what the risk indicators mean.

## Before recording

- Install the release APK and model files on the Galaxy F14; let the phone cool and charge it above 50%.
- For the incoming-SMS shot, turn Wi-Fi and mobile data off but leave cellular service on. Switch airplane mode on for the remaining analysis shots.
- Use these five sample messages: an SBI KYC scam with a link; a Hinglish electricity cut-off threat; a lottery message using a Google Forms link; a genuine SBI UPI alert; and a genuine HDFC OTP.
- Use the phone screen recorder or `adb shell screenrecord`.

## Shot list

| Time | Shot | Narration |
|---|---|---|
| 0:20–0:45 | Receive an SMS with data connections off; show the private alert and open the result | “The message arrives without Wi-Fi or mobile data. Sentinel checks it locally.” |
| 0:45–1:05 | Enable airplane mode | “The rest of the demonstration runs offline.” |
| 1:05–1:30 | Paste the SBI KYC scam and show its risk, cues, and untrusted link | “The SMS model, URL model, and rules contribute signals to one result.” |
| 1:30–2:00 | Show the advice and timing details | “Llama writes advice on the phone. A guard removes unsafe instructions.” |
| 2:00–2:30 | Check the Hinglish threat and trusted-host lottery message | “The detector handles code-mixed text and evaluates the full link, including its path.” |
| 2:30–2:45 | Check the genuine bank alert and OTP | “Low-risk messages use fixed advice and skip Llama.” |
| 2:45–3:00 | Show the Android manifest | “The app has no INTERNET permission.” |
| 3:00–3:30 | Show held-out results in `docs/benchmarks.md` | “English and Hinglish results are strongest; native-script detection still has weak areas.” |
| 3:30–4:00 | Turn airplane mode off | “Message analysis did not require a network connection.” |

## After recording

Confirm the airplane-mode indicator is visible during the offline analysis. Avoid showing pairing codes, debugging ports, or personal notifications. Label every reported performance value with the phone model and test conditions.
