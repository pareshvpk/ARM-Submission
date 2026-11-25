# Calibration result (DT-2)

Pre-registered acceptance (evaluated on the test half only): risky recall drop <= 1.0 pp vs baseline,
ham FPR not higher than baseline, shoe-store promotion extra not high.

- Dump rows: 13104 (calibration 6548, test 6550, extra 6)
- Verdict: chosen candidate passes pre-registered acceptance on the test half

## Baseline (test half)

n=6550, risky recall 0.7812, ham FPR 0.1334 (tp=2528 fn=708 fp=442 tn=2872)

## Chosen candidate (test half)

Params: {'temperature': 3.0, 'scam_weight': 0.9, 'unwanted_weight': 0.5, 'medium_threshold': 0.4, 'high_threshold': 0.7}

n=6550, risky recall 0.7726, ham FPR 0.1053 (tp=2500 fn=736 fp=349 tn=2965)

## Per-language (test half)

Baseline:
- Assamese: recall 0.621, ham FPR 0.279 (n=500)
- Bengali: recall 0.824, ham FPR 0.059 (n=500)
- English: recall 0.947, ham FPR 0.004 (n=605)
- Gujarati: recall 0.588, ham FPR 0.032 (n=500)
- Hindi: recall 0.937, ham FPR 0.137 (n=500)
- Hinglish: recall 0.928, ham FPR 0.000 (n=500)
- Kannada: recall 0.332, ham FPR 0.008 (n=500)
- Kashmiri: recall 0.644, ham FPR 0.040 (n=500)
- Malayalam: recall 0.722, ham FPR 0.159 (n=500)
- Marathi: recall 0.913, ham FPR 0.123 (n=500)
- Odia: recall 0.867, ham FPR 0.000 (n=218)
- Punjabi: recall 0.891, ham FPR 0.254 (n=500)
- Tamil: recall 0.948, ham FPR 0.333 (n=227)
- Telugu: recall 0.872, ham FPR 0.459 (n=500)

Chosen:
- Assamese: recall 0.593, ham FPR 0.190 (n=500)
- Bengali: recall 0.836, ham FPR 0.035 (n=500)
- English: recall 0.954, ham FPR 0.007 (n=605)
- Gujarati: recall 0.596, ham FPR 0.028 (n=500)
- Hindi: recall 0.952, ham FPR 0.141 (n=500)
- Hinglish: recall 0.944, ham FPR 0.000 (n=500)
- Kannada: recall 0.328, ham FPR 0.008 (n=500)
- Kashmiri: recall 0.556, ham FPR 0.016 (n=500)
- Malayalam: recall 0.665, ham FPR 0.119 (n=500)
- Marathi: recall 0.898, ham FPR 0.068 (n=500)
- Odia: recall 0.878, ham FPR 0.000 (n=218)
- Punjabi: recall 0.898, ham FPR 0.209 (n=500)
- Tamil: recall 0.935, ham FPR 0.280 (n=227)
- Telugu: recall 0.885, ham FPR 0.391 (n=500)

## Extra texts (levels before -> after)

- faf232ebfc9b: high -> high
- ee888aa6cdf1: high -> high
- 76e0d4208b89: high -> high
- 124e895d3bee: high -> high
- e08d7fa2ef27: high -> medium
- 7bf1a4fac05f: low -> low
