# Standout upgrades for PS3 Sentinel (judge-facing)

Research only. Repo: C:\Users\user\arm-ps3. Topic: features and evidence that lift judging scores for the Bharat AI-SoC PS3 entry. Ranked by estimated gain/effort. First video deadline 23 Nov 2026.

Summary: The entry already has strong engineering evidence (KV-cache-style not applicable; here: 34.3 ms detector p95, 0 egress, 2.38 GB RAM, 0.977 macro F1) but its weakest judging surfaces are (a) Indian-real detection quality (FPR 5.1 % vs 1 % target) and no held-out confusion matrix, (b) no user-facing highlighting/privacy proof/demo polish, (c) no Indian-script cues beyond Hinglish, (d) no energy numbers, (e) no Arm-per-feature story. The proposals below target judging criteria in docs/requirements.md S8 (detection quality, on-device performance, user effectiveness) and PS3 briefing evaluation (precision/recall/FPR/latency, memory/CPU, clarity/action completion).

## P1 Privacy proof artifact (zero network permission + packet capture)
- What: Ship a reproducible privacy proof: manifest shows no INTERNET permission, tcpdump capture over a 10-minute session with airplane-mode toggle, and a one-page method note.
- Why it matters: NFR-06, NFR-07; judging "operation without internet" and privacy. Competitors (Bitdefender, Norton, Truecaller) are cloud-only (docs/recon/competitors.md).
- Expected gain: +1-2 judging points on impact/privacy; low risk of rejection.
- Effort: 4 h; files: docs/privacy_proof.md, deploy scripts, manifest check.
- Risk: Android tcpdump needs root; use emulator/adb? Must not claim unmeasured. Mark phone as "permission-based proof only".
- Fits before 23 Nov 2026: yes.

## P2 Highlight risky words in UI (cue spans)
- Why it matters: FR-11, S6 Option A "risk + highlighted cues"; user effectiveness criterion.
- Evidence: cue spans with offsets already produced (sentinel/detectors.py, Cues.kt); tests validate offsets (tests/test_pipeline.py).
- Expected gain: visible UX differentiator; +1 point.
- Effort: 4-6 h; files: android UI layouts/MainActivity.kt, sentinel CLI output.
- Risk: cue span mismatch across languages (B1-B3 bugs) must be fixed first.
- Fits before 23 Nov 2026: yes.

## P3 Held-out Indian test set with confusion matrix
- What: Collect 200+ hand-labelled Indian SMS (scam/ham/unwanted), evaluate separately, publish confusion matrix and per-source F1/FPR.
- Why it matters: NFR-01 (F1>=0.95, FPR<=1%); benchmarks.md shows Indian-real FPR 5.1% fail; v4 held-out sources show generalisation gaps.
- Evidence: measured v5 Indian-real FPR 5.1% (benchmarks.md); v4 per-source F1 (bolewara 0.978, karanverma19 0.863, Punjab 0.376).
- Expected gain: credibility; without it judges see inflated metrics. +2 points.
- Effort: 12-20 h data + 4 h eval; files: data/, bench/, docs.
- Risk: FPR may worsen; report honestly.
- Fits before 23 Nov 2026: partial (100 messages feasible).

## P4 Indian scripts and languages (Hindi Devanagari, Tamil, Telugu, Hinglish)
- What: Add cue lexicons and normalisation for Devanagari Hindi, Tamil, Telugu scripts; keep romanised Hinglish. Test on real messages.
- Why it matters: FR-12, NFR-10; competitors Truecaller has Indian languages but cloud; ours offline. Judging impact.
- Evidence: model is multilingual MiniLM (engineering_report.md) but cues are English/Hinglish only (sentinel/detectors.py, Cues.kt). Inference.
- Expected gain: strong differentiator for Indian judges; +2 points if at least Hindi Devanagari + Hinglish demo.
- Effort: 16-24 h; files: detectors.py, Cues.kt, tests, trusted_domains.
- Risk: cue parity bugs (F1/FRAG); model may not handle script well; need eval.
- Fits before 23 Nov 2026: partial (Hinglish + Devanagari cues feasible; Tamil/Telugu after).

## P5 QR-code phishing detection
- What: Add an offline QR decoder (e.g. ZXing) to extract URLs from QR images/screenshots and run the URL classifier; show risk.
- Why it matters: Bitdefender Scamio supports QR (competitors.md); PS3 phishing URL sub-detector (FR-04); user effectiveness.
- Evidence: sourced: Bitdefender Scamio QR support (competitors.md). Our URL classifier exists (1.1 MB).
- Expected gain: feature parity with commercial; +1 point.
- Effort: 8-12 h Android; Python maybe optional. Files: android image picker, UrlClassifier.
- Risk: camera permissions, offline decoding accuracy; avoid network.
- Fits before 23 Nov 2026: yes if image-picker only (no live camera).

## P6 WhatsApp and other app notifications
- What: Use NotificationListenerService to scan notifications from WhatsApp/Telegram/SMS and alert on scam risk.
- Why it matters: FR-01 covers SMS; competitors (Bitdefender) operate across WhatsApp. Indian users receive scams via WhatsApp.
- Evidence: inference; Android notification access permission. Sourced: Bitdefender channels include WhatsApp (competitors.md).
- Expected gain: relevance to Indian market; +1-2 points.
- Effort: 12-18 h; files: new service, manifest, UI.
- Risk: privacy concerns (notification content), battery, permission friction; must keep offline.
- Fits before 23 Nov 2026: maybe (basic notification text scan feasible).

## P7 Voice-call scam follow-up SMS
- What: Detect SMS that reference a recent/missed call or "call back" patterns; optionally read call log (permission) to correlate.
- Why it matters: Chakshu reports voice-call scams (competitors.md); Indian "digital arrest" scams use calls + SMS.
- Evidence: cue patterns already include urgency/threat; add call-related cues. Inference for call-log correlation.
- Expected gain: Indian threat coverage; +1 point.
- Effort: 6-10 h; files: detectors.py, Cues.kt, cues list.
- Risk: call log permission increases privacy scrutiny; keep optional.
- Fits before 23 Nov 2026: yes (cue-only, no call log).

## P8 On-device adaptive feedback (no cloud)
- What: Add "Was this helpful? / Report wrong" that updates a local allow/block list or adjusts fusion thresholds locally; no network.
- Why it matters: user effectiveness; Chakshu is reactive reporting; ours can adapt privately.
- Evidence: inference; NFR-07 privacy.
- Expected gain: novelty + privacy story; +1 point.
- Effort: 10-16 h; files: storage, fusion, UI.
- Risk: threshold drift, gaming; keep bounded and reversible.
- Fits before 23 Nov 2026: no (basic feedback logging yes; adaptation no).

## P9 Energy per message measurement
- Why it matters: NFR-09 thermal/stability; judging on-device performance; BhashaBridge publishes thermal data.
- Evidence: sourced: BhashaBridge SUSTAINED_STRESS_TEST.md (thermal drift, DVFS); our soak shows 56.5 C. Inference for energy numbers.
- Expected gain: stronger hardware story; +1 point.
- Effort: 6-10 h; files: bench, docs.
- Risk: need reliable power measurement; avoid false precision.

## P10 Arm-specific story (per-feature gains)
- What: Document and demo what each Arm feature gave: NEON/dotprod throughput 50->152-207 tok/s, i8mm, SVE2/SME 4-9%, KleidiAI, HWCAP-derived thread policy, 9-device matrix.
- Why it matters: judging Arm-specific category; BhashaBridge scored strong by publishing negative results and per-ISA gains.
- Expected gain: +2-3 points; credibility.
- Effort: 6-8 h docs + 2 h demo; files: docs/arm_story.md, benchmarks.
- Risk: must not claim SME on unsupported devices; cite BhashaBridge as method reference only.
- Fits before 23 Nov 2026: yes.

## P11 Demo video script upgrade
- What: Produce 3-4 min video following docs/demo_script.md but add: airplane-mode proof, highlighted cues, held-out metrics slide, Arm story, privacy proof.
- Why it matters: deliverable #3; briefing asks live offline run on actual device.
- Evidence: sourced: docs/demo_script.md exists; BhashaBridge JUDGE_SCORECARD.md notes demo weakness ("no demo video").
- Expected gain: essential for qualification; +2-3 points.
- Effort: 4-6 h; files: demo video, docs.
- Risk: phone heating affects Llama decode; record cool.
- Fits before 23 Nov 2026: yes.

## P12 Confusion matrix and per-threat metrics in report
- What: Publish confusion matrices for SMS (3 classes) and URL (benign/phishing) on held-out sets, plus per-threat-type (UPI, KYC, courier, electricity, digital arrest, job, loan).
- Why it matters: S8 detection quality; NFR-01 acceptance requires bench metrics JSON.
- Evidence: measured macro F1 0.977; Indian subset macro F1 0.870. Inference for per-threat breakdown.
- Expected gain: judge trust; +1 point.
- Effort: 4-6 h; files: bench, docs.
- Fits before 23 Nov 2026: yes.

## P13 User study (NFR-11)
- What: Run a 10-user comprehension/action-completion study with non-technical users; report results table.
- Why it matters: NFR-11, judging user effectiveness.
- Evidence: sourced: requirements NFR-11; BhashaBridge JUDGE_SCORECARD impact weakness "no field validation".
- Expected gain: +1-2 points if completed.
- Effort: 8-12 h; files: docs/user_study.md.
- Risk: scheduling; small sample.
- Fits before 23 Nov 2026: no (post-deadline).

## P14 Model integrity check (SHA-256)
- What: Ship expected SHA-256 for each model and refuse to load tampered models.
- Why it matters: SEC-01; judging robustness/security.
- Evidence: sourced: security review SEC-01.
- Expected gain: security credibility; +0.5-1 point.
- Effort: 4-6 h; files: ModelStore.kt, cli.py, assets.
- Risk: build complexity; model updates require hash updates.
- Fits before 23 Nov 2026: yes.

## P15 Prompt-injection guard for Llama
- What: Strip Llama control tokens and cap message length before build_prompt (Python+Kotlin).
- Why it matters: SEC-02; safety.
- Evidence: sourced: security review SEC-02.
- Expected gain: safety story; +0.5 point.
- Effort: 3-4 h; files: advisor.py, Advisor.kt.
- Risk: over-stripping may alter meaning; keep minimal.
- Fits before 23 Nov 2026: yes.

## P16 Cross-language parity tests (cues/fusion/URL)
- What: Add parity tests so Python and Kotlin cues/fusion/URL indicators agree; fix B1-B4.
- Evidence: measured: review P3, B1-B4; tests currently only prompt/tokenizer.
- Expected gain: correctness; +0.5 point.
- Effort: 6-10 h; files: tests.
- Risk: exposes more bugs; budget fix time.
- Fits before 23 Nov 2026: yes.

## P17 Detector interface + dummy detector test
- What: Implement FR-14 detector interface and demonstrate a dummy detector registering without pipeline changes.
- Why it matters: FR-14, modularity for Phase 2 network detector.
- Evidence: inference; requirements FR-14.
- Expected gain: architecture credibility; +0.5 point.
- Effort: 4-6 h; files: sentinel/, android.
- Risk: refactor churn.
- Fits before 23 Nov 2026: yes.

## P18 Network detector (Phase 2) preview
- What: Add a pcap replay + simple classifier demo for network anomalies (Option C) as a separate documented pipeline.
- Why it matters: PDF/Phase 2; completeness.
- Evidence: sourced: requirements FR-15; competitors Suricata/Zeek.
- Expected gain: +1 point but large effort; defer.
- Effort: 30+ h.
- Risk: scope creep before deadline.
- Fits before 23 Nov 2026: no.

## Ranking (gain/effort)
1. P1 privacy proof (high/low) - yes
2. P2 highlighting (high/low) - yes
3. P10 Arm story (high/low) - yes
4. P11 demo video (high/low) - yes
5. P15 prompt injection (med/low) - yes
6. P14 model integrity (med/low) - yes
7. P16 parity tests (med/med) - yes
8. P3 held-out eval (high/med) - partial
9. P12 confusion matrix (med/low) - yes
10. P9 energy (med/med) - yes
11. P5 QR (med/med) - yes
12. P7 voice-call cues (med/low) - yes
13. P4 languages (high/high) - partial
14. P6 WhatsApp (med/high) - maybe
15. P8 adaptive feedback (med/high) - no
16. P13 user study (med/high) - no
17. P17 detector interface (low/med) - yes
18. P18 network detector (med/very high) - no
