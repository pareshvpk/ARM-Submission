# Benchmarks and detection quality

This page summarizes device-independent held-out evaluation and Android device measurements. Raw phone reports are in `docs/device_tests/`; evaluation scripts and model scores are under `bench/`.

## Held-out detection quality

| Evaluation | Data | Result |
|---|---:|---|
| SMS v5 | 62,176 messages, template-grouped split | Macro F1 0.977; risky false-positive rate 0.87%; ROC-AUC 0.999 |
| SMS Indian-real subset | 631 messages | Macro F1 0.870; false-positive rate 5.1%; scam recall 0.90 |
| URL v2 | 658k URLs | Precision 0.975; recall 0.741; F1 0.842; false-positive rate 0.81% |
| Shipped fusion rules | 13,098 held-out rows | F1 0.817; recall 0.766; false-positive rate 10.9% |
| Shipped SMS v6ml, English | Held-out incoming-message path | Recall 89.8%; false alarms 0.0%; F1 0.946 |
| Shipped SMS v6ml, Hinglish | Held-out incoming-message path | Recall 85.0%; false alarms 0.2%; F1 0.918 |

The shipped-rule multilingual evaluation is strongest in English and Hinglish. Some native-script cells remain weak, including Kannada recall and Telugu ham false positives. One evaluation source is synthetic. See `bench/heldout/sim_script_gate_20261110.json` and the held-out tooling for full slice definitions and caveats.

## Android model footprint

| Model | Format | Approximate size |
|---|---|---:|
| SMS int8 | ExecuTorch | 51 MB |
| SMS hybrid fallback | ExecuTorch | 112 MB |
| URL v2 character CNN | ExecuTorch fp32 | 1.1 MB |
| Llama 3.2 1B advice model | SpinQuant INT4 | 1.14 GB |

Phones without Arm dot-product support use the hybrid SMS model. The phone installer chooses the appropriate file based on CPU features.

## Android device measurements

Values below are warm SMS detection ranges and Llama time-to-first-token ranges from the device reports. The first message after launch can be slower.

| Phone | CPU | SMS detection (ms) | Llama first token (ms) |
|---|---|---:|---:|
| moto g73 5G | Dimensity 930 | 13–73 | 1,018–1,635 |
| Galaxy F12 | Exynos 850 | 2,829–10,443 | 8,687–12,637 |
| Galaxy M31 | Exynos 9611 | 382–5,588 | 4,440–7,572 |
| Galaxy M32 | Helio G80 | 25–1,033 | 2,102–3,377 |
| Galaxy F14 5G | Exynos 1330 | 15–761 | 1,197–1,961 |

These measurements come from the device reports in `docs/device_tests/`. Phone decode speed declines as the device warms; results should be read with each report's test conditions.

## Offline and privacy evidence

The Android manifest omits network permissions. The phone offline run is recorded under `bench/results/f14_offline_20261105/`. Android packet capture was not measured because the test phone was not rooted; see `docs/privacy_proof.md` for the scope of the evidence.
