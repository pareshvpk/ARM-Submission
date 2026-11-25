**Decision basis:** the shipped-rules run below is the decision basis: V0 is the real `sentinel.fusion.fuse()` with `sentinel/data/rules.json` as it now ships (temperature 3.0, scam weight 0.9), and the baseline-parameter run earlier is kept only as the reproduction check.

**Verdict:** on the shipped rules the gate is **REJECTED**; no variant passes (a), (b) and (c) together, so the gate is rejected on this basis.

# Script-gate simulation (ML-1, 2026-11-10)

Offline only. No app code was changed. The simulation joins the held-out messages to `bench/heldout/calib_20261108/dump_20261108.csv` by the documented text hash, replays the real fusion path, and scores the gate variants on the rows whose dominant script is not Latin.

## Reproduction check

- Method: real sentinel.fusion.fuse() with FUSION_RULES temporarily set to the dump-time baseline (temperature 1.0, scam weight 1.0, unwanted weight 0.5).
- Joined rows: 13098 (missing joins: 0).
- Level mismatches against the dump column: **0** (0.00%), limit 0.5%: **PASS**.
- Risk mismatches (absolute): 0.
- Replica vs real `fuse()` mismatches: 0.
- For transparency, replaying the shipped post-calibration rules (temperature 3.0, scam weight 0.9) against this dump differs on 820 rows (6.26%).

The dumped fused_level is the pre-calibration baseline recorded in calibrate.BASELINE_PARAMS and calibration.md (temperature 1.0, scam weight 1.0). The shipped rules.json is the calibrated candidate (temperature 3.0, scam weight 0.9), so replaying the shipped parameters against the dump is expected to differ and is reported only for transparency.

## Gated rows

10811 of 13098 rows are gated (82.5%); 2287 are not gated and are kept exactly at V0.

| Language | Rows | Gated | Share |
|---|---:|---:|---:|
| Assamese | 1000 | 1000 | 100.0% |
| Bengali | 1000 | 997 | 99.7% |
| English | 1209 | 0 | 0.0% |
| Gujarati | 1000 | 1000 | 100.0% |
| Hindi | 1000 | 1000 | 100.0% |
| Hinglish | 1000 | 0 | 0.0% |
| Kannada | 1000 | 975 | 97.5% |
| Kashmiri | 1000 | 1000 | 100.0% |
| Malayalam | 1000 | 975 | 97.5% |
| Marathi | 1000 | 1000 | 100.0% |
| Odia | 435 | 435 | 100.0% |
| Punjabi | 1000 | 1000 | 100.0% |
| Tamil | 454 | 454 | 100.0% |
| Telugu | 1000 | 975 | 97.5% |

| Dominant script | Rows | Gated | Share |
|---|---:|---:|---:|
| Arabic | 1000 | 1000 | 100.0% |
| Bengali | 1997 | 1997 | 100.0% |
| Devanagari | 2000 | 2000 | 100.0% |
| Gujarati | 1000 | 1000 | 100.0% |
| Gurmukhi | 1000 | 1000 | 100.0% |
| Kannada | 975 | 975 | 100.0% |
| Latin | 2287 | 0 | 0.0% |
| Malayalam | 975 | 975 | 100.0% |
| Odia | 435 | 435 | 100.0% |
| Tamil | 454 | 454 | 100.0% |
| Telugu | 975 | 975 | 100.0% |

## Overall results (all 13,098 rows)

Predicted risky means level medium or high. Non-gated rows are identical to V0 in every variant.

| Variant | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| V0 | 13098 | 0.772 | 14.01% | 0.846 | 0.807 |
| V1 | 13098 | 0.609 | 1.89% | 0.970 | 0.748 |
| V2 | 13098 | 0.594 | 1.17% | 0.981 | 0.740 |
| V3 | 13098 | 0.528 | 0.24% | 0.995 | 0.690 |
| V4 | 13098 | 0.604 | 1.19% | 0.981 | 0.748 |

## Gated rows only (acceptance basis)

| Variant | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| V0 | 10811 | 0.736 | 16.64% | 0.809 | 0.771 |
| V1 | 10811 | 0.535 | 2.21% | 0.959 | 0.686 |
| V2 | 10811 | 0.515 | 1.36% | 0.973 | 0.674 |
| V3 | 10811 | 0.434 | 0.25% | 0.994 | 0.605 |
| V4 | 10811 | 0.528 | 1.38% | 0.974 | 0.685 |

## Per language (all rows)

### V0

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.580 | 28.80% | 0.668 | 0.621 |
| Bengali | 1000 | 0.792 | 5.00% | 0.941 | 0.860 |
| English | 1209 | 0.930 | 0.36% | 0.997 | 0.962 |
| Gujarati | 1000 | 0.574 | 3.40% | 0.944 | 0.714 |
| Hindi | 1000 | 0.950 | 12.60% | 0.883 | 0.915 |
| Hinglish | 1000 | 0.916 | 0.00% | 1.000 | 0.956 |
| Kannada | 1000 | 0.306 | 0.80% | 0.975 | 0.466 |
| Kashmiri | 1000 | 0.650 | 3.20% | 0.953 | 0.773 |
| Malayalam | 1000 | 0.738 | 20.20% | 0.785 | 0.761 |
| Marathi | 1000 | 0.908 | 13.60% | 0.870 | 0.888 |
| Odia | 435 | 0.842 | 0.00% | 1.000 | 0.914 |
| Punjabi | 1000 | 0.892 | 28.80% | 0.756 | 0.818 |
| Tamil | 454 | 0.967 | 35.66% | 0.645 | 0.774 |
| Telugu | 1000 | 0.886 | 47.80% | 0.650 | 0.750 |

### V1

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.300 | 4.80% | 0.862 | 0.445 |
| Bengali | 1000 | 0.618 | 0.00% | 1.000 | 0.764 |
| English | 1209 | 0.930 | 0.36% | 0.997 | 0.962 |
| Gujarati | 1000 | 0.496 | 0.40% | 0.992 | 0.661 |
| Hindi | 1000 | 0.948 | 12.40% | 0.884 | 0.915 |
| Hinglish | 1000 | 0.916 | 0.00% | 1.000 | 0.956 |
| Kannada | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Kashmiri | 1000 | 0.504 | 0.00% | 1.000 | 0.670 |
| Malayalam | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Marathi | 1000 | 0.584 | 0.00% | 1.000 | 0.737 |
| Odia | 435 | 0.842 | 0.00% | 1.000 | 0.914 |
| Punjabi | 1000 | 0.610 | 1.40% | 0.978 | 0.751 |
| Tamil | 454 | 0.896 | 0.00% | 1.000 | 0.945 |
| Telugu | 1000 | 0.510 | 5.40% | 0.904 | 0.652 |

### V2

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.300 | 3.20% | 0.904 | 0.450 |
| Bengali | 1000 | 0.580 | 0.00% | 1.000 | 0.734 |
| English | 1209 | 0.930 | 0.36% | 0.997 | 0.962 |
| Gujarati | 1000 | 0.490 | 0.40% | 0.992 | 0.656 |
| Hindi | 1000 | 0.914 | 10.00% | 0.901 | 0.908 |
| Hinglish | 1000 | 0.916 | 0.00% | 1.000 | 0.956 |
| Kannada | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Kashmiri | 1000 | 0.504 | 0.00% | 1.000 | 0.670 |
| Malayalam | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Marathi | 1000 | 0.570 | 0.00% | 1.000 | 0.726 |
| Odia | 435 | 0.811 | 0.00% | 1.000 | 0.895 |
| Punjabi | 1000 | 0.578 | 0.60% | 0.990 | 0.730 |
| Tamil | 454 | 0.896 | 0.00% | 1.000 | 0.945 |
| Telugu | 1000 | 0.442 | 0.80% | 0.982 | 0.610 |

### V3

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Bengali | 1000 | 0.442 | 1.40% | 0.969 | 0.607 |
| English | 1209 | 0.930 | 0.36% | 0.997 | 0.962 |
| Gujarati | 1000 | 0.464 | 0.00% | 1.000 | 0.634 |
| Hindi | 1000 | 0.448 | 0.00% | 1.000 | 0.619 |
| Hinglish | 1000 | 0.916 | 0.00% | 1.000 | 0.956 |
| Kannada | 1000 | 0.304 | 0.00% | 1.000 | 0.466 |
| Kashmiri | 1000 | 0.488 | 0.60% | 0.988 | 0.653 |
| Malayalam | 1000 | 0.396 | 0.20% | 0.995 | 0.567 |
| Marathi | 1000 | 0.490 | 0.00% | 1.000 | 0.658 |
| Odia | 435 | 0.605 | 0.00% | 1.000 | 0.754 |
| Punjabi | 1000 | 0.488 | 0.00% | 1.000 | 0.656 |
| Tamil | 454 | 0.593 | 0.74% | 0.982 | 0.740 |
| Telugu | 1000 | 0.490 | 0.20% | 0.996 | 0.657 |

### V4

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.300 | 2.20% | 0.932 | 0.454 |
| Bengali | 1000 | 0.594 | 1.40% | 0.977 | 0.739 |
| English | 1209 | 0.930 | 0.36% | 0.997 | 0.962 |
| Gujarati | 1000 | 0.488 | 0.40% | 0.992 | 0.654 |
| Hindi | 1000 | 0.888 | 9.00% | 0.908 | 0.898 |
| Hinglish | 1000 | 0.916 | 0.00% | 1.000 | 0.956 |
| Kannada | 1000 | 0.304 | 0.00% | 1.000 | 0.466 |
| Kashmiri | 1000 | 0.516 | 0.60% | 0.989 | 0.678 |
| Malayalam | 1000 | 0.396 | 0.20% | 0.995 | 0.567 |
| Marathi | 1000 | 0.560 | 0.00% | 1.000 | 0.718 |
| Odia | 435 | 0.805 | 0.00% | 1.000 | 0.892 |
| Punjabi | 1000 | 0.540 | 0.40% | 0.993 | 0.699 |
| Tamil | 454 | 0.896 | 0.74% | 0.988 | 0.939 |
| Telugu | 1000 | 0.532 | 0.60% | 0.989 | 0.692 |


## Per dominant script (all rows)

### V0

| Script | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Arabic | 1000 | 0.650 | 3.20% | 0.953 | 0.773 |
| Bengali | 1997 | 0.685 | 16.90% | 0.802 | 0.739 |
| Devanagari | 2000 | 0.929 | 13.10% | 0.876 | 0.902 |
| Gujarati | 1000 | 0.574 | 3.40% | 0.944 | 0.714 |
| Gurmukhi | 1000 | 0.892 | 28.80% | 0.756 | 0.818 |
| Kannada | 975 | 0.269 | 0.80% | 0.970 | 0.422 |
| Latin | 2287 | 0.929 | 0.19% | 0.998 | 0.962 |
| Malayalam | 975 | 0.724 | 20.20% | 0.773 | 0.748 |
| Odia | 435 | 0.842 | 0.00% | 1.000 | 0.914 |
| Tamil | 454 | 0.967 | 35.66% | 0.645 | 0.774 |
| Telugu | 975 | 0.880 | 47.80% | 0.636 | 0.739 |

### V1

| Script | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Arabic | 1000 | 0.504 | 0.00% | 1.000 | 0.670 |
| Bengali | 1997 | 0.457 | 2.40% | 0.950 | 0.617 |
| Devanagari | 2000 | 0.766 | 6.20% | 0.925 | 0.838 |
| Gujarati | 1000 | 0.496 | 0.40% | 0.992 | 0.661 |
| Gurmukhi | 1000 | 0.610 | 1.40% | 0.978 | 0.751 |
| Kannada | 975 | 0.263 | 0.00% | 1.000 | 0.417 |
| Latin | 2287 | 0.929 | 0.19% | 0.998 | 0.962 |
| Malayalam | 975 | 0.263 | 0.00% | 1.000 | 0.417 |
| Odia | 435 | 0.842 | 0.00% | 1.000 | 0.914 |
| Tamil | 454 | 0.896 | 0.00% | 1.000 | 0.945 |
| Telugu | 975 | 0.484 | 5.40% | 0.895 | 0.628 |

### V2

| Script | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Arabic | 1000 | 0.504 | 0.00% | 1.000 | 0.670 |
| Bengali | 1997 | 0.438 | 1.60% | 0.965 | 0.603 |
| Devanagari | 2000 | 0.742 | 5.00% | 0.937 | 0.828 |
| Gujarati | 1000 | 0.490 | 0.40% | 0.992 | 0.656 |
| Gurmukhi | 1000 | 0.578 | 0.60% | 0.990 | 0.730 |
| Kannada | 975 | 0.263 | 0.00% | 1.000 | 0.417 |
| Latin | 2287 | 0.929 | 0.19% | 0.998 | 0.962 |
| Malayalam | 975 | 0.263 | 0.00% | 1.000 | 0.417 |
| Odia | 435 | 0.811 | 0.00% | 1.000 | 0.895 |
| Tamil | 454 | 0.896 | 0.00% | 1.000 | 0.945 |
| Telugu | 975 | 0.413 | 0.80% | 0.980 | 0.581 |

### V3

| Script | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Arabic | 1000 | 0.488 | 0.60% | 0.988 | 0.653 |
| Bengali | 1997 | 0.369 | 0.70% | 0.981 | 0.536 |
| Devanagari | 2000 | 0.469 | 0.00% | 1.000 | 0.639 |
| Gujarati | 1000 | 0.464 | 0.00% | 1.000 | 0.634 |
| Gurmukhi | 1000 | 0.488 | 0.00% | 1.000 | 0.656 |
| Kannada | 975 | 0.267 | 0.00% | 1.000 | 0.422 |
| Latin | 2287 | 0.929 | 0.19% | 0.998 | 0.962 |
| Malayalam | 975 | 0.364 | 0.20% | 0.994 | 0.533 |
| Odia | 435 | 0.605 | 0.00% | 1.000 | 0.754 |
| Tamil | 454 | 0.593 | 0.74% | 0.982 | 0.740 |
| Telugu | 975 | 0.463 | 0.20% | 0.995 | 0.632 |

### V4

| Script | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Arabic | 1000 | 0.516 | 0.60% | 0.989 | 0.678 |
| Bengali | 1997 | 0.445 | 1.80% | 0.961 | 0.609 |
| Devanagari | 2000 | 0.724 | 4.50% | 0.941 | 0.819 |
| Gujarati | 1000 | 0.488 | 0.40% | 0.992 | 0.654 |
| Gurmukhi | 1000 | 0.540 | 0.40% | 0.993 | 0.699 |
| Kannada | 975 | 0.267 | 0.00% | 1.000 | 0.422 |
| Latin | 2287 | 0.929 | 0.19% | 0.998 | 0.962 |
| Malayalam | 975 | 0.364 | 0.20% | 0.994 | 0.533 |
| Odia | 435 | 0.805 | 0.00% | 1.000 | 0.892 |
| Tamil | 454 | 0.896 | 0.74% | 0.988 | 0.939 |
| Telugu | 975 | 0.507 | 0.60% | 0.988 | 0.670 |

## Pre-registered acceptance

A variant passes only when all three checks hold. Values are shown for each check.

| Variant | (a) English/Hinglish unchanged | (b) Gated ham FPR | (c) Gated recall drop vs V0 | Verdict |
|---|---|---|---|---|
| V1 | PASS (0 of 2209 rows changed) | PASS (2.21%, limit 5.0%) | FAIL (20.14 pp, limit 5.0 pp) | **FAIL** |
| V2 | PASS (0 of 2209 rows changed) | PASS (1.36%, limit 5.0%) | FAIL (22.06 pp, limit 5.0 pp) | **FAIL** |
| V3 | PASS (0 of 2209 rows changed) | PASS (0.25%, limit 5.0%) | FAIL (30.15 pp, limit 5.0 pp) | **FAIL** |
| V4 | PASS (0 of 2209 rows changed) | PASS (1.38%, limit 5.0%) | FAIL (20.76 pp, limit 5.0 pp) | **FAIL** |

No variant passes. The gate reliably cuts the false alarms on gated rows, but every variant loses far more than 5 percentage points of risky recall on those rows, because many native-script risky rows were reaching medium level only through the SMS `unwanted` term.

## Rows where synthetic is false

n = 0. heldout_20261107.csv synthetic values are 'true' and 'mixed'; there are no 'false' rows. The join works, but this table is therefore empty; no result can be reported for a false slice.

## Caveats

- Most rows are synthetic: 12,889 of 13,098 are tagged `synthetic=true`; the remaining 209 carnageiron English rows are `mixed` real/synthetic. No row is tagged `synthetic=false`.
- Labels are the dataset authors', not hand-checked.
- The dump column is the pre-calibration baseline. Reproducing it requires the dump-time parameters (temperature 1.0, scam weight 1.0, unwanted weight 0.5); the shipped rules.json now carries the calibrated candidate (3.0, 0.9). The simulation keeps the dump baseline so V0 is the column under test.
- V4 `temperature-scaled p_scam` uses the same reproduction temperature (1.0), so it equals the dumped raw `p_scam`. The shipped fusion temperature (3.0) would move that boundary.
- `max_untrusted_url_prob` is the processed untrusted URL probability already in the dump; the URL scam threshold is rules.json `url_phishing_label_threshold` (0.5).
- The cap in V3/V4 is 0.3999, just below the medium threshold, and the final score is rounded to 4 decimals before the level is chosen.

## Exploratory (not pre-registered)

These ideas were not part of the acceptance rule and were not scored as variants.

- The closest variant is V1 (drop the unwanted term): gated ham FPR falls from 16.6% to 2.2%, but gated risky recall falls by about 20 points. A softer version might suppress only the `unwanted` label/presentation while leaving the level, or blend the unwanted weight rather than dropping it; that would need its own pre-registered test.
- A cue-aware gate (cap only when the model's top class is `unwanted` and no cue exists) could preserve scam rows, but the dump does not store the model's argmax class, so it cannot be tested from these columns without a new dump.


## Shipped rules run (decision basis)

This is the decision basis. V0 is the real `sentinel.fusion.fuse()` with `sentinel/data/rules.json` exactly as it ships (temperature 3.0, scam weight 0.9). V1 to V4 apply the same variant definitions on top of those shipped rules; V4 uses the shipped temperature for its temperature-scaled `p_scam`. Non-gated rows stay at the real shipped `fuse()` result.

### Overall (all 13,098 rows)

| Variant | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| V0 | 13098 | 0.766 | 10.93% | 0.874 | 0.817 |
| V1 | 13098 | 0.601 | 1.46% | 0.976 | 0.744 |
| V2 | 13098 | 0.521 | 0.14% | 0.997 | 0.685 |
| V3 | 13098 | 0.532 | 0.15% | 0.997 | 0.694 |
| V4 | 13098 | 0.545 | 0.15% | 0.997 | 0.705 |

### Gated rows only (acceptance basis)

| Variant | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| V0 | 10811 | 0.726 | 12.96% | 0.843 | 0.780 |
| V1 | 10811 | 0.522 | 1.69% | 0.967 | 0.679 |
| V2 | 10811 | 0.424 | 0.11% | 0.997 | 0.595 |
| V3 | 10811 | 0.437 | 0.13% | 0.997 | 0.608 |
| V4 | 10811 | 0.453 | 0.13% | 0.997 | 0.623 |

### Per language (all rows)

#### V0

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.556 | 20.20% | 0.734 | 0.633 |
| Bengali | 1000 | 0.826 | 3.40% | 0.960 | 0.888 |
| English | 1209 | 0.936 | 0.55% | 0.995 | 0.965 |
| Gujarati | 1000 | 0.590 | 3.20% | 0.949 | 0.727 |
| Hindi | 1000 | 0.968 | 12.80% | 0.883 | 0.924 |
| Hinglish | 1000 | 0.932 | 0.00% | 1.000 | 0.965 |
| Kannada | 1000 | 0.300 | 0.60% | 0.980 | 0.459 |
| Kashmiri | 1000 | 0.562 | 0.80% | 0.986 | 0.716 |
| Malayalam | 1000 | 0.682 | 14.00% | 0.830 | 0.749 |
| Marathi | 1000 | 0.898 | 7.80% | 0.920 | 0.909 |
| Odia | 435 | 0.853 | 0.00% | 1.000 | 0.920 |
| Punjabi | 1000 | 0.892 | 24.20% | 0.787 | 0.836 |
| Tamil | 454 | 0.945 | 30.88% | 0.672 | 0.785 |
| Telugu | 1000 | 0.898 | 39.20% | 0.696 | 0.784 |

#### V1 (best variant)

| Language | n | Risky recall | FPR on ham | Precision | F1 |
|---|---:|---:|---:|---:|---:|
| Assamese | 1000 | 0.300 | 4.60% | 0.867 | 0.446 |
| Bengali | 1000 | 0.592 | 0.00% | 1.000 | 0.744 |
| English | 1209 | 0.936 | 0.55% | 0.995 | 0.965 |
| Gujarati | 1000 | 0.490 | 0.40% | 0.992 | 0.656 |
| Hindi | 1000 | 0.934 | 11.80% | 0.888 | 0.910 |
| Hinglish | 1000 | 0.932 | 0.00% | 1.000 | 0.965 |
| Kannada | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Kashmiri | 1000 | 0.504 | 0.00% | 1.000 | 0.670 |
| Malayalam | 1000 | 0.300 | 0.00% | 1.000 | 0.462 |
| Marathi | 1000 | 0.576 | 0.00% | 1.000 | 0.731 |
| Odia | 435 | 0.837 | 0.00% | 1.000 | 0.911 |
| Punjabi | 1000 | 0.584 | 0.60% | 0.990 | 0.735 |
| Tamil | 454 | 0.896 | 0.00% | 1.000 | 0.945 |
| Telugu | 1000 | 0.464 | 1.20% | 0.975 | 0.629 |

### Pre-registered acceptance

Same acceptance rule as the baseline run. A variant passes only when all three checks hold.

| Variant | (a) English/Hinglish unchanged | (b) Gated ham FPR | (c) Gated recall drop vs V0 | Verdict |
|---|---|---|---|---|
| V1 | PASS (0 of 2209 rows changed) | PASS (1.69%, limit 5.0%) | FAIL (20.32 pp, limit 5.0 pp) | **FAIL** |
| V2 | PASS (0 of 2209 rows changed) | PASS (0.11%, limit 5.0%) | FAIL (30.19 pp, limit 5.0 pp) | **FAIL** |
| V3 | PASS (0 of 2209 rows changed) | PASS (0.13%, limit 5.0%) | FAIL (28.88 pp, limit 5.0 pp) | **FAIL** |
| V4 | PASS (0 of 2209 rows changed) | PASS (0.13%, limit 5.0%) | FAIL (27.28 pp, limit 5.0 pp) | **FAIL** |

Best variant by the stated rule: **V1**, chosen for the highest gated risky recall among the variants whose gated ham FPR is at most 5%, then lower gated ham FPR.

### Cross-check against the stored calibration evidence

- There is no stored shipped-level column. dump_20261108.csv fused_level is the pre-calibration baseline. The shipped levels are recomputed with calibrate.risk_and_level and the chosen candidate (temperature 3.0, scam weight 0.9), exactly as tests/test_calibration_shipped.py does.
- Shipped V0 against that recomputed reference: **0** level mismatches on 13098 joined rows.
- tests/test_calibration_shipped.py and calibration.md cover all 13,104 dumped rows; this run joins the 13,098 held-out rows.
- Shipped V0 on all joined rows: risky recall **76.60%**, ham FPR **10.93%**.
- docs/benchmarks.md section SMS fusion calibration reports the 6,550-row test half only; the shipped V0 numbers here are over all 13,098 joined rows and are not directly comparable. The docs test-half values are recall 77.26% and FPR 10.53%.

### Shipped-run caveats

- The earlier baseline sections are unchanged and remain the reproduction check against the dump column.
- V4 uses the shipped temperature (3.0) here, so its `p_scam` boundary differs from the baseline-run V4.
