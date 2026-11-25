# PS3 Requirements: On-Device Threat, Phishing and Scam Detection

Bharat AI-SoC Challenge 2026-27, Problem Statement 3. Status: updated 2026-11-10.

## Source key

Every requirement names where it comes from.

| Tag | Source |
|---|---|
| PDF | Official challenge page (Bharat AI-SoC Challenge 2026-27, PS3 section) |
| V mm:ss | Official PS3 briefing video, timestamp in `media/transcript.txt` (not committed); cleaned text in `docs/ps3_transcript.md` |
| S n | Slide n of the briefing video (keyframes checked) |
| R | Gap found in `docs/recon/competitors.md` |
| T | Team decision |
| P | PROPOSED by us; not stated by any source, open to change |

## 1. Scope

### Phase 1 (target 23 Nov 2026)
Primary scenario: **scam SMS detection (video Option A) plus classification of every URL found in the message (Option B as a sub-detector)**. [V 07:01-07:29, S6 "best for a quick end-to-end demo"; T]

- URLs extracted from the SMS and scored by a URL classifier.
- Risk fusion turns detector outputs into structured evidence.
- Llama 3.2 1B Instruct on ExecuTorch writes a short explanation and advice from that evidence.
- UI shows risk level, highlighted cues, explanation and advice.
- Everything runs offline on the device.
- A detector interface that the Phase 2 network detector plugs into without changing the pipeline.

### Phase 2 (target 05 Feb 2027)
- Network traffic detector (Option C): flow/packet metadata, intrusion or anomaly classifier, alerts with key signals. [PDF; V 07:21; S6]
- Classifiers on the Hailo NPU through HailoRT where compatible, as a separate, documented pipeline. [PDF; V 06:23]
- Wider language coverage and user study. [P]

### Out of scope
- Any cloud inference or online reputation lookup at run time. [PDF; V 03:46]
- Automatic actions: clicking or opening links, deleting messages, blocking senders without the user. [V 08:07]
- Malware behaviour analysis on the device (listed in the PDF objective, deferred: no dataset or demo path chosen yet). [T; see open question Q4]

## 2. Functional requirements

| ID | Requirement | Source | Phase | Status | Acceptance test |
|---|---|---|---|---|---|
| FR-01 | Accept SMS text on Android: incoming-SMS notification path plus manual paste/share-to-app. | PDF; V 07:13; T | 1 | done | Send a test SMS to the phone; the app scores it without opening the app manually. Paste path works with SMS permission denied. |
| FR-03 | Extract every URL from the message, including bare domains, shortened links and obfuscated forms (hxxp, spaces around dots). | V 07:47 (suspicious link); P for obfuscation cases | 1 | done | Unit test with 30 crafted messages: all URLs found, no false extraction from plain text. |
| FR-04 | Classify each extracted URL with a local model; return score and indicators (e.g. IP host, lookalike brand, risky TLD, shortener, long subdomain chain). | PDF; S6 Option B | 1 | done | Held-out phishing/benign URL set meets NFR-01; indicators listed in output. |
| FR-05 | Classify the SMS text as scam / not scam with a local model; return score and cue spans (urgency, threat, payment or credential request, impersonation). | PDF; V 07:13; S6 Option A (risk + highlighted cues) | 1 | done | Held-out SMS set meets NFR-01; cue spans map to character offsets in the message. |
| FR-06 | Risk fusion: combine SMS score, URL scores and rule hits into one evidence object {label, score, threshold, indicators, cue spans, detector versions}. | S4 (score + threshold; label, score, indicators) | 1 | done | Same input always gives the same evidence JSON; schema test passes. |
| FR-07 | Llama (Llama 3.2 1B Instruct) on ExecuTorch receives only the evidence object plus the message and writes a short, bounded explanation and advice. Llama never decides the label. | PDF; V 05:32-05:48; S4 design rule | 1 | done | Code review: label comes from fusion only. Output capped (P: 130 tokens, `DEFAULT_MAX_NEW_TOKENS = 130` in `sentinel/advisor.py:651`; FULL tier 130, LIGHT tier 78). Llama output that contradicts the label is replaced by a template. |
| FR-08 | Advice names concrete next steps: do not click, verify via the official app or website, report at sancharsaathi.gov.in (Chakshu) or 1930, block sender. | PDF (remediation); V 03:34, 07:51; R (Chakshu) | 1 | done | Each of 20 scam test cases shows at least one concrete step. |
| FR-09 | Never open, fetch or resolve a URL automatically, including link previews. | V 08:07 | 1 | done | Packet capture during a scan of a URL-bearing message shows no request to that host. |
| FR-10 | Never state certainty; wording uses risk levels (low / medium / high) and "may be". | V 08:07 | 1 | done | Regex check over 100 generated explanations finds no "100%", "definitely", "guaranteed". |
| FR-12 | Cover Indian scam patterns: UPI collect requests, KYC/PAN/Aadhaar update, courier/customs, electricity disconnection, digital arrest, job/task scams, loan apps; English and romanised Hinglish. | R (Indian specialisation gap); T | 1 | partly | Indian test set (at least 200 hand-checked messages, P) reported separately in metrics. |
| FR-13 | Fallback when Llama is unavailable or too slow: show template explanation built from the indicators. | P | 1 | done | Kill the Llama runner; app still shows verdict + template advice. |
| FR-14 | Detector interface: each detector implements `name`, `version`, `score(input) -> evidence part`; fusion loops over registered detectors. | V 07:29 (keep it modular); T | 1 (interface), 2 (network detector) | partly (in progress; interface added 2026-11-10) | A dummy detector registers without changes to fusion or UI code. |

## 3. Non-functional requirements

| ID | Requirement | Source | Phase | Status | Acceptance test |
|---|---|---|---|---|---|
| NFR-01 | Detection quality targets: SMS F1 at least 0.95 and FPR at most 1 % on held-out set; URL F1 at least 0.93, FPR at most 2 %. | Metrics: S8; numbers P | 1 | partly | `bench/` metrics JSON on fixed test split. |
| NFR-05 | Llama quantized for ExecuTorch (XNNPACK, 4-bit weights / 8-bit dynamic activations or the official SpinQuant/QLoRA 1B checkpoint); .pte at most 1.5 GB. Detectors int8 where accuracy loss is under 1 point F1. | PDF (ExecuTorch); V 04:42 (lightweight); numbers P | 1 | done | File sizes + accuracy before/after quantization in report. |
| NFR-06 | Fully offline: all features work with Wi-Fi and mobile data off. | PDF; V 03:46, 06:40, 09:55 | 1 | done | Airplane-mode run recorded in the demo video. |
| NFR-07 | Privacy: no message text, URL or metadata leaves the device; no analytics SDKs. | PDF; V 04:15 | 1 | partly | tcpdump during a 10-minute session shows no egress from the app. |
| NFR-08 | Placement documented: which model runs on Arm CPU (ExecuTorch) and which on Hailo NPU (HailoRT); the two pipelines are separate. | PDF; V 06:23-06:40, 09:41-09:55 | 1 (CPU-only), 2 (NPU) | done | Report table + runtime log line per model naming its device. |
| NFR-10 | Explanation readability: plain words, at most 3 short sentences + at most 3 steps; English first, Hindi/Tamil as stretch. | V 03:26, 08:56; S8; numbers P | 1 | partly | Readability score (Flesch at least 60, P) + small user check (NFR-11). |
| NFR-11 | User effectiveness measured: at least 10 non-technical users, comprehension and action-completion rate recorded. | S8 (clarity, action completion, user understanding); size P | 1 (pilot), 2 (full) | not done | Results table in report. |

## 4. Evaluation and KPI capture

| Judging area [S8] | Metrics we report | How |
|---|---|---|
| Detection quality | Precision, recall, F1, FPR, detection latency, per threat type (SMS, URL; network in Phase 2), Indian subset separately | Fixed train/val/test split, seed recorded, confusion matrices |
| User effectiveness | Explanation clarity, action completion, understanding of risk | Short task-based study with non-technical users |

Every benchmark record carries the fields the video asks for [S9]: device and OS, model and quantization, ExecuTorch version, latency, memory, offline test result. We also log: detector versions, CPU/NPU placement, ambient temperature/throttle state (P).

## 5. Deliverables checklist

| # | Deliverable | Detail | Source |
|---|---|---|---|
| 1 | Source code | Team's own GitHub repo, step-by-step setup scripts, submitted via the challenge form | PDF; S10; V 10:12 |
| 3 | Demo video | End-to-end live run on the actual device, real threat detection, offline | S10; V 10:28, 10:48 |
| 4 | Engineering report | Hardware setup, model configuration, quantization settings, measured KPIs, CPU/NPU placement | PDF; S10; V 10:37 |

Licence for the repo: Apache-2.0 (owner decision 2026-11-12, file `LICENSE`); model files stay under their own terms, including the Llama 3.2 Community Licence.

## 6. Constraints and compliance

- Llama family model for advisory/reasoning, run on device with ExecuTorch as the reference runtime. [PDF; V 06:16]
- Hailo NPU only through HailoRT, separate from the ExecuTorch Llama pipeline, documented. [PDF; V 06:23]
- Original work, owned by the team, no IP violation. Recon informed features only; no competitor code or models reused. [PDF]
- Llama 3.2 Community Licence terms followed (attribution, acceptable use). [P]
- Dataset licences checked before use: UCI SMS Spam Collection, PhishTank/OpenPhish (feed terms), PhiUSIIL, CIC-IDS2017, UNSW-NB15, any Indian SMS set. [PDF optional datasets; P]
- Test on real target hardware, not only laptop or cloud notebooks. [V 09:33]

## 7. Open questions for organisers

Send to tech-queries@armbharatchallenge.com with PS3 in the subject (technical questions about a problem statement; general support is support@armbharatchallenge.com; both are on the official page, checked 2026-11-10). [PDF] Status 2026-11-10: not yet sent. Q1 is answered by the page: 23 Nov 2026 and 05 Feb 2027.

- Q1. [Answered] Deadlines: 23 Nov 2026 and 5 Feb 2027 are binding, per the official page. (Slide 10 says 23 Nov 2026 / 05 Feb 2027, the page earlier showed 30 Nov 2026 / 10 Feb 2027).
- Q2. Is one primary scenario (SMS + embedded URL) enough for Phase 1 qualification, given the page lists all capabilities?
- Q3. Is a Llama 3.2 1B variant acceptable, or is a minimum size expected?
- Q4. Is malware behaviour detection expected in Phase 1, or can it be deferred like the network detector?
- Q5. Will organisers provide evaluation datasets or a common test harness?
