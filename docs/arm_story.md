# Android Arm support

PS3 Sentinel runs its Android inference locally with ExecuTorch and XNNPACK. The app reads CPU feature flags at runtime and selects the suitable SMS model path. Phones without Arm dot-product support use NEON with the hybrid SMS export; phones with dot-product support use the int8 export.

## Tested phones

| Phone | CPU | Selected path |
|---|---|---|
| Galaxy M31 | Exynos 9611, Armv8.0 | NEON |
| Galaxy F12 | Exynos 850 | NEON |
| moto g73 5G | Dimensity 930 | DOTPROD |
| Galaxy M32 | Helio G80 | DOTPROD |
| Galaxy F14 5G | Exynos 1330 | DOTPROD |

The local ExecuTorch 1.5.1 Android AAR is built for Armv8.0 with `-march=armv8-a -moutline-atomics`. It avoids the Armv8.1 LSE requirement found in the stock Maven AAR and was checked on the Galaxy M31. See `docs/build_executorch_armv8.md` and the reports under `docs/device_tests/`.

## Kernel availability

The AAR includes NEON, dot-product, fp16, i8mm, SME, and SME2 kernels. The tested phones select NEON or DOTPROD. i8mm and SME-family acceleration have not been measured on these phones, so no speedup is claimed for those paths.

Per-device timings and memory measurements are listed in `docs/benchmarks.md` and the linked device reports.
