# Local ExecuTorch AAR

`executorch-android-1.5.1-armv8.aar` here is optional. `android/app/build.gradle.kts`
uses it when it exists and otherwise falls back to the Maven artifact
`org.pytorch:executorch-android:1.5.1`.

It is the Armv8.0 build for DT-9: the Maven AAR contains inline Armv8.1 LSE
atomics and crashes with SIGILL on phones such as the Galaxy M31 (Exynos 9611,
Cortex-A73/A53). The local file is built from the same ExecuTorch v1.5.1 tag
with `-march=armv8-a -moutline-atomics`, so newer phones still use LSE at run
time.

Build it on Ubuntu 22.04 (WSL), then rebuild the app:

```bash
bash deploy/android/build_executorch_aar.sh ~/et-armv8
```

The resulting `.aar` is copied here automatically. See
[docs/build_executorch_armv8.md](../../../docs/build_executorch_armv8.md) for
prerequisites, the verification command and the measured crash details.

`*.aar` files in this directory are not tracked by git.
