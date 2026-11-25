# PS3 briefing video: cleaned transcript

Source: official PS3 briefing video (11:29). Cleaned transcript supplied by the team, cross-checked against the
Whisper transcript (media/transcript.txt, not committed) and the slide keyframes. Section headings follow the slides.

Speakers: Arm / challenge host (opening remarks); Dr. Vijay Kumar, MS and PhD, IIT Delhi (technical walkthrough).

## Part 1: Opening address (00:00-01:37)

Welcome to the second edition of Bharat AI SoC Challenge, officially launched by Arm and the Ministry of IT at
Semicon India. Supported by the UK Government through the UK-India Technology and Security Initiative, with IIT Delhi
as the lead mentor institute. Meta is on board. Open to students, developers and working professionals.

## Part 2: PS3 walkthrough (01:47-11:29)

Goal: detect threats on the device, explain the risk in easy language, and help users stay safe without sending
personal data to the cloud.

### 01 The problem and our goal
Threats come from network traffic, phishing links and scam messages. Traditional tools show complex alerts that
ordinary users cannot understand. Five features: network monitoring, phishing detection, scam message detection,
simple explanation, recommended action. Must run locally on Arm hardware and keep working without internet.

### 02 Why edge AI
Privacy (data stays on device), speed (no network round trip), reliability (works offline). Edge devices have limited
memory, compute and battery, so models must be lightweight and must not overheat the device.

### 03 Reference architecture: a modular pipeline from signals to safe action
- Collect: SMS, URL or network flow; clean, parse, normalise, extract features.
- Detect: classifier / anomaly model, rules + ML.
- Explain: risk fusion (score + threshold) sends structured evidence to Llama running through ExecuTorch.
- Recommend: Llama explains the risk simply and advises the user.
- Design rule (slide): use the detector to produce structured evidence (label, score, indicators). Use Llama for a
  short, bounded explanation and remediation advice, not as the sole threat detector.

### 04 Required technology
Llama family model for reasoning/advice, run on device with ExecuTorch. With a Hailo NPU, run compatible ML models via
HailoRT on the NPU and Llama via ExecuTorch on the Arm CPU. Keep both pipelines separate; must work without internet.

### 05 Pick a focused use case
Do not build everything at once; pick one primary scenario, keep the architecture modular.
- Option A, SMS scam: SMS text, spam/scam classifier, risk + highlighted cues (best for a quick end-to-end demo).
- Option B, phishing URL: URL string/features, URL classifier or reputation feeds, suspicious indicators + safe action.
- Option C, network traffic: flow/packet metadata, anomaly or intrusion classifier, alert with key signals.

### 06 Example
Message: Account locked. Verify now. The system detects urgency and a suspicious link; the language model explains
why it may be a scam and advises verifying through the official website or app. The system must never automatically
click links or claim its predictions are always correct.

### 07 Evaluation
- Detection quality: precision, recall, false-positive rate, detection latency across threat types.
- On-device performance: inference time, memory, CPU/accelerator load, operation without internet.
- User effectiveness: clarity of explanations, action completion, user understanding of risk.
Suggested milestones: data pipelines and baseline detectors; local inference and risk scoring; explanations and
remediation; robustness, privacy and usability tests on target hardware.

### 08 Target hardware
AI HAT (HailoRT for compatible models, ExecuTorch for Llama on CPU); Arm Linux edge appliance (service-style).
Do not rely only on laptop or cloud simulation. Show clearly which model runs on the NPU and which on the CPU.
Capture: device/OS, model and quantization, ExecuTorch version, latency, memory, offline test verification.

### 09 Deliverables and deadlines
1. Source code: GitHub repository with step-by-step setup scripts.
2. On-device application: compiled binary (APK for Android, wheel or binary for Linux).
3. Demonstration video: end-to-end live walkthrough of real threat detection on the actual device, working offline.
4. Engineering report: hardware setup, model configuration, quantization settings, measured KPIs.

Deadlines (slide): Open Qualifying 23 Nov 2026; PoC Development 05 Feb 2027. The challenge page says 30 Nov 2026 and
10 Feb 2027; plan for the earlier dates until confirmed.
Hub: https://arm-education.github.io/Arm-Developer-Labs/Bharat_AI_SoC_2026_27.html. Support: support@armbharatchallenge.com.
