# Armv8.0 ExecuTorch build (DT-9)

## Why

The Galaxy M31 (Samsung SM-M315F, Exynos 9611: 4x Cortex-A73 + 4x Cortex-A53,
Armv8.0, Android 12) crashes about 5 s after every launch while loading the SMS
model. The crash is `SIGILL, code 1 (ILL_ILLOPC)` in `libexecutorch_jni.so`,
frame `0x1cff90`, called from `org.pytorch.executorch.Module.execute` through
`SmsClassifier.isDynamic`. No message can be classified, and every incoming SMS
would hit the same crash path.

Measured facts:

- The faulting instruction word is `0xf8f60108`, which is `LDADDAL`, an
  Armv8.1 LSE atomic. The Exynos 9611 has no atomics extension.
- The stock Maven AAR `org.pytorch:executorch-android:1.5.1` contains about
  188 inline LSE atomic instructions across its `arm64-v8a` native libraries.
- The device reports only `fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid`:
  no LSE atomics, no dot product, no fp16.

The app's Java/Kotlin layer cannot fix this: the illegal instruction is in the
prebuilt native library. DT-9's long-term fix is therefore a rebuild of the
same ExecuTorch version for the Armv8.0 baseline.

## What is built

`deploy/android/build_executorch_aar.sh` clones `pytorch/executorch` at tag
`v1.5.1` and builds the official Android library helper
(`scripts/build_android_library.sh`) for **arm64-v8a only** with:

```
-march=armv8-a -moutline-atomics
```

`-march=armv8-a` keeps every instruction at the Armv8.0 baseline.
`-moutline-atomics` moves atomics out of line, where the Arm C runtime selects
LSE instructions at run time on cores that advertise them. Newer phones keep
the fast path; the M31 gets the baseline path.

The build keeps:

- XNNPACK with KleidiAI and its run-time CPU dispatch (dot product, fp16 and
  i8mm kernels are still selected at run time on capable cores);
- the LLM runner extension (`LlmModule` with `prefillPrompt` and `generate`);
- the same Java/Kotlin API, version and behaviour.

Only the AAR changes. `android/app/build.gradle.kts` prefers
`android/app/libs/executorch-android-1.5.1-armv8.aar` when it exists and logs
which ExecuTorch artifact it uses. Without the local file it keeps using the
Maven artifact exactly as before.

## Prerequisites

Run on Ubuntu 22.04 (WSL is fine). Nothing here needs root; the script only uses
the work directory and the user's home.

- Git, curl (or wget), unzip, JDK 17+, Python 3.10+ and a C++ compiler. If one
  is missing the script prints the one apt line to run:
  `sudo apt-get update && sudo apt-get install -y git curl unzip openjdk-17-jdk python3 python3-venv build-essential`
- An Android SDK with platform 34 (or accept the SDK licences and let Gradle
  download it). Set `ANDROID_HOME` / `ANDROID_SDK`, or keep the SDK at
  `~/Android/Sdk`.
- An Android NDK. Any r27.x or r28.x found through `ANDROID_NDK`,
  `ANDROID_NDK_HOME`, `ANDROID_NDK_ROOT`, the SDK's `ndk/` directory or
  `~/.local` is used. If none is found, the script downloads NDK r27c into
  `~/.local`. ExecuTorch 1.5.1 documents NDK r28c; both are accepted.
- Python `cmake` (>= 3.26) and `ninja` are installed into a venv in the work
  directory, so they do not touch the system Python.

The script also installs ExecuTorch's Python build requirements into that venv
(including the pinned PyTorch nightly). This needs network access and is the
slow part of the first run.

## How to run

```bash
bash deploy/android/build_executorch_aar.sh              # work dir ~/et-armv8
bash deploy/android/build_executorch_aar.sh /path/to/dir # explicit work dir
```

The script is long-running (tens of minutes, several GB). It is not run by the
test suite.

What it does, in order:

1. checks host tools and prints the apt line for anything missing;
2. creates `<work>/.venv`, installs `cmake` and `ninja`, then ExecuTorch's
   Python requirements;
3. clones `https://github.com/pytorch/executorch.git` at `v1.5.1` with
   submodules (or reuses the existing clone and checks out the tag);
4. verifies in the cloned tree that `scripts/build_android_library.sh` exists,
   honours `ANDROID_ABIS`, consumes `ANDROID_NDK` and `BUILD_AAR_DIR`, passes
   the Android CMake toolchain file, and that `CMakePresets.json` has the
   `android-arm64-v8a` preset; it stops with a clear error if any is absent;
5. locates or downloads the NDK and locates the Android SDK;
6. runs the official helper with `ANDROID_ABIS=arm64-v8a`,
   `CMAKE_GENERATOR=Ninja`, `BUILD_AAR_DIR=<work>/aar-out` and the baseline
   flags as `-DCMAKE_C_FLAGS` / `-DCMAKE_CXX_FLAGS` cache variables
   (the script `unset`s `CFLAGS`/`CXXFLAGS` so the flags never reach host
   sub-builds such as `flatc`, then injects them via a patched copy of the
   helper, `scripts/build_android_library.armv8.sh`);
7. checks `CMakeCache.txt` contains `-moutline-atomics` and
   `ANDROID_ABI=arm64-v8a`; if the cache predates the flags it is discarded and
   reconfigured (set `ET_REUSE_BUILD=1` to keep it);
8. verifies the AAR contains `jni/arm64-v8a/libexecutorch_jni.so`, copies it to
   `android/app/libs/executorch-android-1.5.1-armv8.aar`, prints its size and
   SHA-256, and runs the LSE scanner.

Useful overrides: `ET_NDK_VERSION=r28c`, `ET_USE_PINNED_TORCH=1`,
`ET_SKIP_PYTHON_SETUP=1`, `ET_FORCE_PYTHON_SETUP=1`, `ET_REUSE_BUILD=1`.

## Verify the result

```bash
python deploy/android/check_no_lse.py \
  android/app/libs/executorch-android-1.5.1-armv8.aar
```

The scanner opens each arm64 `.so` in the AAR, finds its `.text` section
through the ELF section headers, and counts LSE atomic instruction words in
`.text` only:

- LDADD/SWP family: `(word & 0x3f200c00) == 0x38200000`
- CAS family: `(word & 0x3fa07c00) == 0x08a07c00`

Scanning only `.text` matters: whole executable `PT_LOAD` segments also
cover string/rodata bytes, and LSE-looking byte patterns in that data are
not instructions (the stock library counts about 196 across executable
segments but only about 44 in `.text`). It prints counts per library and
exits 1 if any inline LSE is found in `libexecutorch` or
`libexecutorch_jni` (the measured `LDADDAL`, `0xf8f60108`, matches the first
mask). A clean scan of the local AAR is the acceptance signal that inline
LSE is gone.

The build script also runs the scanner and prints its output. A failing
scan is fatal: the build exits 1 instead of shipping an AAR that would
SIGILL on Armv8.0 phones such as the Galaxy M31. With `-moutline-atomics`,
the out-of-line compiler-rt helper bodies may still contain LSE
instructions behind a run-time HWCAP check; those helpers are expected and
excluded. When a symbol table exists, words inside `__aarch64_*` outline
helper symbols are excluded by symbol. When the library is stripped, an
LSE word immediately followed by `RET` (`0xd65f03c0`) counts as an outline
helper body for the same reason. Any other LSE word in `.text` counts as
inline and fails the scan, which means the flags did not reach the
compiler.

After building, rebuild/install the app. Gradle prints either:

```
ExecuTorch: using local AAR .../android/app/libs/executorch-android-1.5.1-armv8.aar
```

or, when the file is absent:

```
ExecuTorch: using Maven artifact org.pytorch:executorch-android:1.5.1
```

The AAR is intentionally not committed (`android/app/libs/*.aar` is in
`.gitignore`); it is a build product.
