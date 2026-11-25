#!/usr/bin/env bash
#
# build_executorch_aar.sh - build ExecuTorch v1.5.1 for Armv8.0 Android phones.
#
# DT-9: the stock org.pytorch:executorch-android:1.5.1 AAR contains inline
# Armv8.1 LSE atomics (about 188 of them) and SIGILLs on Armv8.0 cores such as
# the Galaxy M31 (Exynos 9611, Cortex-A73/A53). This script rebuilds the same
# ExecuTorch version with -march=armv8-a (the Armv8.0 baseline) and
# -moutline-atomics, so LSE is still selected at run time on newer cores.
#
# The official helper scripts/build_android_library.sh from the cloned
# ExecuTorch tree does the actual build. Its documented inputs are used:
#   * ANDROID_HOME / ANDROID_SDK / ANDROID_NDK
#   * ANDROID_ABIS=arm64-v8a (build one ABI only)
#   * BUILD_AAR_DIR (where the helper copies executorch.aar)
#   * CMAKE_C_FLAGS / CMAKE_CXX_FLAGS (passed as CMake cache vars of the
#     Android configure only; env CFLAGS/CXXFLAGS are unset because they also
#     reach host sub-builds such as flatc, which rejects -moutline-atomics)
# The helper exposes no option for extra compiler flags, so the baseline flags
# are injected into the patched helper copy via -DCMAKE_C_FLAGS/-DCMAKE_CXX_FLAGS
# and checked in CMakeCache.txt afterwards.
#
# Everything it installs stays inside the user's home directory (the work dir
# venv and $HOME/.local for a downloaded NDK). Root is never required; when a
# system package is missing, the matching apt line is printed for the user.
#
# Usage:
#   bash deploy/android/build_executorch_aar.sh [WORK_DIR]
#
# WORK_DIR defaults to ~/et-armv8. The finished AAR is copied to
# android/app/libs/executorch-android-1.5.1-armv8.aar.
#
# Long-running (tens of minutes, several GB). This script is meant to be run by
# a human or the manager, not by the test suite.
#
# Environment overrides:
#   ET_NDK_VERSION=<r27c>          NDK to download when none is installed
#   ET_USE_PINNED_TORCH=1          pass --use-pt-pinned-commit to requirements
#   ET_SKIP_PYTHON_SETUP=1         reuse the venv without installing requirements
#   ET_FORCE_PYTHON_SETUP=1        re-run the requirements install
#   ET_REUSE_BUILD=1               keep an existing configure cache
#
set -euo pipefail

ET_VERSION="1.5.1"
ET_TAG="v${ET_VERSION}"
ARM_BASELINE_FLAGS="-march=armv8-a -moutline-atomics"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
DEST_DIR="${REPO_ROOT}/android/app/libs"
DEST_AAR="${DEST_DIR}/executorch-android-${ET_VERSION}-armv8.aar"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi
if [[ $# -gt 1 ]]; then
  echo "usage: $(basename "$0") [WORK_DIR]" >&2
  exit 2
fi

WORK_DIR="${1:-${HOME}/et-armv8}"
mkdir -p -- "${WORK_DIR}"
WORK_DIR="$(cd -- "${WORK_DIR}" && pwd)"
ET_SRC="${WORK_DIR}/executorch"
VENV_DIR="${WORK_DIR}/.venv"
VENV_PY="${VENV_DIR}/bin/python"
AAR_OUT="${WORK_DIR}/aar-out"
LOCAL_TOOLS="${HOME}/.local"

APT_LINE="sudo apt-get update && sudo apt-get install -y git curl unzip openjdk-17-jdk python3 python3-venv build-essential"

log() { printf '\n== %s\n' "$*" >&2; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command '$1' not found. Install it with:
  ${APT_LINE}"
}

# ---------------------------------------------------------------------------
# Prerequisites that live in the user's home
# ---------------------------------------------------------------------------

check_host_tools() {
  need_cmd git
  need_cmd python3
  need_cmd java
  need_cmd unzip

  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    die "curl or wget is required to download the NDK. Install it with:
  ${APT_LINE}"
  fi

  if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
    die "a C++ compiler is required to build the ExecuTorch Python tokenizer helper. Install it with:
  ${APT_LINE}"
  fi

  local java_major
  java_major="$(java -version 2>&1 | awk -F'"' '/version/ {print $2}' | cut -d. -f1)"
  if [[ "${java_major}" == "1" ]]; then
    java_major="$(java -version 2>&1 | awk -F'"' '/version/ {print $2}' | cut -d. -f2)"
  fi
  [[ -n "${java_major}" && "${java_major}" -ge 17 ]] \
    || die "JDK 17 or newer is required (found: ${java_major:-unknown}). Install it with:
  ${APT_LINE}"

  local py_version
  py_version="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  if ! printf '3.10\n%s\n' "${py_version}" | sort -V -C; then
    die "Python 3.10 or newer is required (found ${py_version}). Install it with:
  ${APT_LINE}"
  fi
  log "Host tools OK (Java ${java_major}, Python ${py_version})"
}

setup_venv() {
  if [[ ! -x "${VENV_PY}" ]]; then
    log "Creating Python venv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || die "python3 -m venv failed. Install python3-venv with:
  ${APT_LINE}"
  fi
  export PATH="${VENV_DIR}/bin:${PATH}"
  log "Installing cmake and ninja into the venv"
  "${VENV_PY}" -m pip install --disable-pip-version-check -q --upgrade pip
  "${VENV_PY}" -m pip install --disable-pip-version-check -q "cmake>=3.26,<4.0.0" ninja
  command -v cmake >/dev/null 2>&1 || die "cmake was not installed into ${VENV_DIR}"
  command -v ninja >/dev/null 2>&1 || die "ninja was not installed into ${VENV_DIR}"
  log "cmake: $(cmake --version | head -n1)"
  log "ninja: $(ninja --version)"
}

download_ndk() {
  local version="$1"
  local dir_name="android-ndk-${version}"
  local zip="${LOCAL_TOOLS}/${dir_name}-linux.zip"
  local url="https://dl.google.com/android/repository/${dir_name}-linux.zip"
  local dest="${LOCAL_TOOLS}/${dir_name}"

  if [[ -f "${dest}/NOTICE" ]]; then
    printf '%s\n' "${dest}"
    return 0
  fi

  mkdir -p -- "${LOCAL_TOOLS}"
  log "Downloading Android NDK ${version} into ${LOCAL_TOOLS}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 30 -o "${zip}" "${url}"
  else
    wget -O "${zip}" "${url}"
  fi
  unzip -q -o "${zip}" -d "${LOCAL_TOOLS}"
  rm -f -- "${zip}"
  [[ -f "${dest}/NOTICE" ]] || die "NDK download did not produce ${dest}/NOTICE"
  printf '%s\n' "${dest}"
}

find_ndk() {
  local candidate path sdk
  for candidate in "${ANDROID_NDK:-}" "${ANDROID_NDK_HOME:-}" "${ANDROID_NDK_ROOT:-}"; do
    if [[ -n "${candidate}" && -f "${candidate}/NOTICE" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  for sdk in "${ANDROID_HOME:-}" "${ANDROID_SDK:-}" "${ANDROID_SDK_ROOT:-}" \
             "${HOME}/Android/Sdk" "${HOME}/android-sdk" "${HOME}/.android/sdk"; do
    [[ -n "${sdk}" ]] || continue
    for path in "${sdk}"/ndk/27.* "${sdk}"/ndk/28.*; do
      if [[ -f "${path}/NOTICE" ]]; then
        printf '%s\n' "${path}"
        return 0
      fi
    done
  done
  for path in "${LOCAL_TOOLS}"/android-ndk-r27* "${LOCAL_TOOLS}"/android-ndk-r28*; do
    if [[ -f "${path}/NOTICE" ]]; then
      printf '%s\n' "${path}"
      return 0
    fi
  done
  return 1
}

setup_ndk() {
  local ndk documented
  if ndk="$(find_ndk)"; then
    log "Using installed Android NDK: ${ndk}"
  else
    ndk="$(download_ndk "${ET_NDK_VERSION:-r27c}")"
    log "Using downloaded Android NDK: ${ndk}"
  fi
  [[ -f "${ndk}/build/cmake/android.toolchain.cmake" ]] \
    || die "${ndk} is not a usable NDK (missing build/cmake/android.toolchain.cmake)"
  documented="$(grep -RhoE 'NDK r[0-9]+[a-z]?' "${ET_SRC}/docs/source" 2>/dev/null | head -n1 || true)"
  if [[ -n "${documented}" ]]; then
    log "ExecuTorch ${ET_VERSION} documents ${documented}; this build accepts NDK r27 or that version"
  fi
  ANDROID_NDK="${ndk}"
  export ANDROID_NDK
}

find_sdk() {
  local candidate
  for candidate in "${ANDROID_HOME:-}" "${ANDROID_SDK:-}" "${ANDROID_SDK_ROOT:-}" \
                   "${HOME}/Android/Sdk" "${HOME}/android-sdk" "${HOME}/.android/sdk"; do
    if [[ -n "${candidate}" && -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

setup_sdk() {
  local sdk
  if ! sdk="$(find_sdk)"; then
    die "Android SDK not found. Install Android Studio or the command-line tools and set ANDROID_HOME/ANDROID_SDK (no root needed), for example:
  sdkmanager --sdk_root=\"\$HOME/android-sdk\" \"platforms;android-34\" \"build-tools;34.0.0\" \"platform-tools\""
  fi
  if [[ ! -d "${sdk}/platforms" ]]; then
    printf 'WARNING: %s/platforms is missing; Gradle will try to download the SDK platform (licenses must be accepted).\n' "${sdk}" >&2
  fi
  ANDROID_HOME="${sdk}"
  ANDROID_SDK="${sdk}"
  export ANDROID_HOME ANDROID_SDK
  log "Using Android SDK: ${sdk}"
}

# ---------------------------------------------------------------------------
# Source tree
# ---------------------------------------------------------------------------

clone_executorch() {
  if [[ ! -d "${ET_SRC}/.git" ]]; then
    log "Cloning pytorch/executorch at ${ET_TAG} into ${ET_SRC}"
    git clone --branch "${ET_TAG}" --depth 1 --recurse-submodules \
      --shallow-submodules https://github.com/pytorch/executorch.git "${ET_SRC}"
  else
    if ! git -C "${ET_SRC}" rev-parse -q --verify "refs/tags/${ET_TAG}" >/dev/null; then
      log "Fetching tag ${ET_TAG}"
      git -C "${ET_SRC}" fetch --depth 1 origin "refs/tags/${ET_TAG}:refs/tags/${ET_TAG}"
    fi
    log "Checking out ${ET_TAG}"
    git -C "${ET_SRC}" checkout -q "${ET_TAG}"
  fi

  local actual
  actual="$(git -C "${ET_SRC}" describe --tags --exact-match 2>/dev/null || true)"
  [[ "${actual}" == "${ET_TAG}" ]] \
    || die "${ET_SRC} is at '${actual:-unknown}', expected ${ET_TAG}"

  log "Updating submodules"
  git -C "${ET_SRC}" submodule sync --recursive >/dev/null
  git -C "${ET_SRC}" submodule update --init --recursive --depth 1
}

verify_build_tree() {
  local helper="${ET_SRC}/scripts/build_android_library.sh"
  [[ -f "${helper}" ]] || die "ExecuTorch ${ET_VERSION} has no ${helper}; refusing to guess a build entry point"
  grep -q 'ANDROID_ABIS' "${helper}" \
    || die "${helper} does not honour ANDROID_ABIS; refusing to build both ABIs"
  grep -q 'ANDROID_NDK' "${helper}" \
    || die "${helper} does not consume ANDROID_NDK"
  grep -q 'CMAKE_TOOLCHAIN_FILE' "${helper}" \
    || die "${helper} does not pass the Android CMake toolchain file"
  grep -q 'BUILD_AAR_DIR' "${helper}" \
    || die "${helper} does not consume BUILD_AAR_DIR; cannot locate the AAR reliably"
  grep -q '"name": "android-arm64-v8a"' "${ET_SRC}/CMakePresets.json" \
    || die "CMakePresets.json has no android-arm64-v8a preset"
  log "Build helper and arm64-v8a preset found in the ExecuTorch tree"
}

install_python_requirements() {
  local marker="${VENV_DIR}/.et-requirements-${ET_VERSION}"
  if [[ "${ET_SKIP_PYTHON_SETUP:-0}" == "1" ]]; then
    log "ET_SKIP_PYTHON_SETUP=1: not installing ExecuTorch Python requirements"
    return 0
  fi
  if [[ -f "${marker}" && "${ET_FORCE_PYTHON_SETUP:-0}" != "1" ]]; then
    log "ExecuTorch Python requirements already installed (${marker})"
    return 0
  fi
  [[ -f "${ET_SRC}/install_requirements.sh" ]] \
    || die "ExecuTorch ${ET_VERSION} has no install_requirements.sh; cannot set up the Python build environment"
  log "Installing ExecuTorch Python requirements into the venv (network)"
  local extra=()
  if [[ "${ET_USE_PINNED_TORCH:-0}" == "1" ]]; then
    extra+=(--use-pt-pinned-commit)
  fi
  (
    cd -- "${ET_SRC}"
    PYTHON_EXECUTABLE="${VENV_PY}" bash ./install_requirements.sh "${extra[@]}"
  )
  touch "${marker}"
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

ensure_fresh_configure() {
  local cache="$1/CMakeCache.txt"
  if [[ "${ET_REUSE_BUILD:-0}" == "1" || ! -f "${cache}" ]]; then
    return 0
  fi
  if ! grep -q -- "-moutline-atomics" "${cache}"; then
    log "Existing configure cache lacks the baseline flags; removing it"
    rm -rf -- "$1"
  fi
}

patch_custom_ops_march() {
  # extension/llm/custom_ops/CMakeLists.txt appends -march=armv8.2-a+dotprod to
  # custom_ops' PUBLIC compile options. It then leaks into every target that links
  # custom_ops, including the JNI layer (measured: ExecuTorchJni::execute_method,
  # Module::~Module and shared_ptr<Tensor> code got inline LDADDAL, which is the
  # SIGILL seen on the Galaxy M31). op_sdpa.cpp includes torchao int8 kernels that
  # need vdotq_s32, so custom_ops itself must keep +dotprod (measured: removing it
  # fails to compile). Fix: base it on armv8-a (dot product but no LSE atomics) and
  # make the options PRIVATE so they no longer leak into the JNI layer. The dotprod
  # code only runs in the quantized-KV-cache attention path. XNNPACK and KleidiAI keep
  # their per-file -march and runtime dispatch (dotprod, i8mm, SME2 on newer cores).
  local f="${ET_SRC}/extension/llm/custom_ops/CMakeLists.txt"
  [[ -f "${f}" ]] || die "missing ${f}"
  if ! grep -q -- '-march=armv8-a+dotprod' "${f}"; then
    sed -i 's/-march=armv8\.2-a+dotprod/-march=armv8-a+dotprod/' "${f}"
  fi
  sed -i 's/target_compile_options(custom_ops PUBLIC \${_common_compile_options})/target_compile_options(custom_ops PRIVATE ${_common_compile_options})/' "${f}"
  grep -q -- '-march=armv8-a+dotprod' "${f}" \
    || die "could not rebase custom_ops -march in ${f}"
  grep -q 'target_compile_options(custom_ops PRIVATE' "${f}" \
    || die "could not make custom_ops compile options PRIVATE in ${f}"
  log "custom_ops: -march=armv8-a+dotprod, compile options PRIVATE"
}

build_aar() {
  patch_custom_ops_march
  local cache="${ET_SRC}/cmake-out-android-arm64-v8a/CMakeCache.txt"
  ensure_fresh_configure "${ET_SRC}/cmake-out-android-arm64-v8a"
  mkdir -p -- "${AAR_OUT}"
  rm -f -- "${AAR_OUT}/executorch.aar"

  log "Configuring and building arm64-v8a with: ${ARM_BASELINE_FLAGS}"
  (
    cd -- "${ET_SRC}"
    export ANDROID_ABIS=arm64-v8a
    export EXECUTORCH_CMAKE_BUILD_TYPE=Release
    export BUILD_AAR_DIR="${AAR_OUT}"
    export CMAKE_GENERATOR=Ninja
    export PYTHON_EXECUTABLE="${VENV_PY}"
    # The official helper has no option for extra compiler flags, and CFLAGS in
    # the environment also reaches host-side sub-builds (flatc, built with the
    # x86 gcc, which rejects -moutline-atomics). So pass the flags as CMake cache
    # variables of the Android configure only, via a patched copy of the helper.
    unset CFLAGS CXXFLAGS
    local helper_copy="scripts/build_android_library.armv8.sh"
    sed "s#-DCMAKE_TOOLCHAIN_FILE=\"\${ANDROID_NDK}/build/cmake/android.toolchain.cmake\" \\\\#&\n    -DCMAKE_C_FLAGS=\"${ARM_BASELINE_FLAGS}\" -DCMAKE_CXX_FLAGS=\"${ARM_BASELINE_FLAGS}\" \\\\#" \
      scripts/build_android_library.sh > "${helper_copy}"
    grep -q -- "-DCMAKE_CXX_FLAGS=\"${ARM_BASELINE_FLAGS}\"" "${helper_copy}" \
      || die "could not inject the baseline flags into ${helper_copy}"
    bash "./${helper_copy}"
  )

  [[ -f "${cache}" ]] || die "configure did not produce ${cache}"
  grep -q -- "-moutline-atomics" "${cache}" \
    || die "the compiler flags did not reach CMake (no -moutline-atomics in ${cache})"
  grep -Eq '^ANDROID_ABI:[^=]*=arm64-v8a$' "${cache}" \
    || die "CMake did not configure for arm64-v8a only (${cache})"
  log "Verified baseline flags and arm64-v8a ABI in CMakeCache.txt"
}

install_result() {
  local aar_src="${AAR_OUT}/executorch.aar"
  if [[ ! -f "${aar_src}" ]]; then
    aar_src="$(find "${ET_SRC}/extension/android/executorch_android/build/outputs/aar" \
      -maxdepth 1 -name '*.aar' -print -quit 2>/dev/null || true)"
  fi
  [[ -n "${aar_src}" && -f "${aar_src}" ]] \
    || die "build finished but no .aar was produced"

  unzip -l "${aar_src}" | grep -E 'arm64-v8a/libexecutorch(_jni)?.so' >/dev/null \
    || die "${aar_src} does not contain jni/arm64-v8a/libexecutorch.so or libexecutorch_jni.so"
  if unzip -l "${aar_src}" | grep -E 'x86_64/|x86/' >/dev/null; then
    printf 'WARNING: %s contains a non-arm64 ABI directory.\n' "${aar_src}" >&2
  fi

  mkdir -p -- "${DEST_DIR}"
  cp -f -- "${aar_src}" "${DEST_AAR}"
  log "Copied $(basename "${aar_src}") -> ${DEST_AAR}"
  log "AAR size: $(du -h "${DEST_AAR}" | cut -f1)"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${DEST_AAR}"
  fi

  log "Checking ${DEST_AAR} for inline LSE atomics"
  set +e
  "${VENV_PY}" "${REPO_ROOT}/deploy/android/check_no_lse.py" "${DEST_AAR}"
  local scan_status=$?
  set -e
  if [[ ${scan_status} -eq 0 ]]; then
    log "check_no_lse.py: clean"
  else
    die "check_no_lse.py reported inline LSE atomics in libexecutorch/libexecutorch_jni (exit ${scan_status}); inline LSE would SIGILL on Armv8.0 phones such as the Galaxy M31, so the build fails instead of shipping a crashing AAR. Inspect the counts above."
  fi
}

main() {
  log "ExecuTorch ${ET_VERSION} Armv8.0 AAR build (DT-9)"
  log "Work dir: ${WORK_DIR}"
  check_host_tools
  setup_venv
  clone_executorch
  verify_build_tree
  setup_ndk
  setup_sdk
  install_python_requirements
  build_aar
  install_result
  log "Done: ${DEST_AAR}"
  log "Rebuild the app so android/app/build.gradle.kts picks up the local AAR."
}

main "$@"
