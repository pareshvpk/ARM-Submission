#!/usr/bin/env bash
# scripts/install_phone.sh
# Install PS3 Sentinel on an Android phone over adb from a folder of release assets.
#
# Usage:
#   bash scripts/install_phone.sh [release_folder]
# Default: ./release

set -euo pipefail

RELEASE_DIR="${1:-./release}"

echo "=========================================================="
echo "PS3 Sentinel: Android Phone Installation"
echo "=========================================================="
echo ""
echo "Release assets can be downloaded via:"
echo "  GitHub CLI: gh release download phase1-submission --repo Vishnu-3727/ps3-sentinel --dir \"$RELEASE_DIR\""
echo "  Browser:    https://github.com/Vishnu-3727/ps3-sentinel/releases/tag/phase1-submission"
echo ""

# 1. Check adb and one connected device
if ! command -v adb >/dev/null 2>&1; then
    echo "ERROR: adb command not found on PATH. Please install Android platform-tools." >&2
    exit 1
fi

DEVICE_COUNT=$(adb devices | grep -v "^List of devices" | grep -c "device$" || true)
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "ERROR: No connected Android device found via adb. Connect a device with USB debugging enabled." >&2
    exit 1
elif [ "$DEVICE_COUNT" -gt 1 ]; then
    echo "ERROR: Multiple devices connected ($DEVICE_COUNT). Please connect only one device." >&2
    adb devices
    exit 1
fi

DEVICE_SERIAL=$(adb devices | grep -v "^List of devices" | grep "device$" | head -n1 | awk '{print $1}')
echo "Connected device: $DEVICE_SERIAL"
echo ""

if [ ! -d "$RELEASE_DIR" ]; then
    echo "ERROR: Release folder not found: $RELEASE_DIR" >&2
    exit 1
fi

# 2. Verify assets against SHA256SUMS
SUMS_FILE="$RELEASE_DIR/SHA256SUMS"
if [ ! -f "$SUMS_FILE" ]; then
    echo "ERROR: SHA256SUMS not found in $RELEASE_DIR" >&2
    exit 1
fi

sha256_check() {
    local file_name="$1"
    local file_path="$RELEASE_DIR/$file_name"
    if [ ! -f "$file_path" ]; then
        echo "ERROR: Required asset file missing: $file_name" >&2
        exit 1
    fi
    local expected_hash
    expected_hash=$(grep "[[:space:]]\*\{0,1\}$file_name$" "$SUMS_FILE" | awk '{print $1}' | head -n1 | tr '[:upper:]' '[:lower:]')
    if [ -z "$expected_hash" ]; then
        echo "ERROR: $file_name is not listed in $SUMS_FILE" >&2
        exit 1
    fi
    local actual_hash
    if command -v sha256sum >/dev/null 2>&1; then
        actual_hash=$(sha256sum "$file_path" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    elif command -v shasum >/dev/null 2>&1; then
        actual_hash=$(shasum -a 256 "$file_path" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    else
        echo "ERROR: Neither sha256sum nor shasum found on system." >&2
        exit 1
    fi

    if [ "$actual_hash" != "$expected_hash" ]; then
        echo "ERROR: SHA-256 mismatch for $file_name!" >&2
        echo "  Expected: $expected_hash" >&2
        echo "  Actual:   $actual_hash" >&2
        exit 1
    fi
    echo "  [OK] $file_name"
}

echo "Verifying release assets against SHA256SUMS..."
BASE_ASSETS=(
    "ps3-sentinel-1.0.apk"
    "url_cnn_v2.pte"
    "vocab.json"
    "id_map.json"
    "sms_vocab.txt"
    "llama.pte"
    "tokenizer.model"
)

for asset in "${BASE_ASSETS[@]}"; do
    sha256_check "$asset"
done

for opt_model in "sms_int8.pte" "sms_fp32.pte"; do
    if [ -f "$RELEASE_DIR/$opt_model" ]; then
        sha256_check "$opt_model"
    fi
done
echo "Asset integrity verification passed."
echo ""

# 3. adb install -r the APK
APK_PATH="$RELEASE_DIR/ps3-sentinel-1.0.apk"
echo "Installing APK: $APK_PATH..."
adb install -r "$APK_PATH"
echo "APK installed successfully."
echo ""

# 4. Launch the app once so its folder exists
echo "Launching app to initialize app data directories..."
adb shell am start --user 0 -W -n org.ps3.sentinel/.ui.HomeActivity
sleep 2

# 5. Read the Features line of /proc/cpuinfo
echo "Checking CPU features from /proc/cpuinfo..."
FEATURES_LINE=$(adb shell cat /proc/cpuinfo | grep -m 1 "^Features" | sed 's/^Features[[:space:]]*:[[:space:]]*//' || true)

PUSH_INT8=false
PUSH_FP32=false

if [ -n "$FEATURES_LINE" ]; then
    echo "Detected Features: $FEATURES_LINE"
    if echo "$FEATURES_LINE" | grep -qw "asimddp"; then
        echo "CPU has Arm dot product (asimddp): selecting sms_int8.pte"
        PUSH_INT8=true
    else
        echo "CPU lacks Arm dot product (no asimddp): selecting sms_fp32.pte"
        PUSH_FP32=true
    fi
else
    echo "WARNING: Could not read Features line from /proc/cpuinfo; pushing both sms_int8.pte and sms_fp32.pte" >&2
    PUSH_INT8=true
    PUSH_FP32=true
fi

# 6. Push models to /sdcard/Android/data/org.ps3.sentinel/files/models/
REMOTE_MODELS_DIR="/sdcard/Android/data/org.ps3.sentinel/files/models/"
adb shell mkdir -p "$REMOTE_MODELS_DIR"

FILES_TO_PUSH=(
    "url_cnn_v2.pte"
    "vocab.json"
    "id_map.json"
    "sms_vocab.txt"
    "llama.pte"
    "tokenizer.model"
)

if [ "$PUSH_INT8" = true ]; then
    sha256_check "sms_int8.pte"
    FILES_TO_PUSH+=("sms_int8.pte")
fi
if [ "$PUSH_FP32" = true ]; then
    sha256_check "sms_fp32.pte"
    FILES_TO_PUSH+=("sms_fp32.pte")
fi

echo ""
echo "Pushing model files to device..."
TOTAL_BYTES=0
declare -a PUSHED_SUMMARY=()

for file_name in "${FILES_TO_PUSH[@]}"; do
    SRC_PATH="$RELEASE_DIR/$file_name"
    FILE_BYTES=$(wc -c < "$SRC_PATH" | tr -d ' ')
    TOTAL_BYTES=$((TOTAL_BYTES + FILE_BYTES))
    SIZE_MB=$(awk "BEGIN {printf \"%.2f\", $FILE_BYTES / 1048576}")
    echo "  Pushing $file_name (${SIZE_MB} MB)..."
    adb push "$SRC_PATH" "${REMOTE_MODELS_DIR}${file_name}"
    PUSHED_SUMMARY+=("  - $file_name: ${SIZE_MB} MB")
done

# 7. Print what was pushed and the total size
echo ""
echo "=========================================================="
echo "Summary of pushed files:"
echo "=========================================================="
for rec in "${PUSHED_SUMMARY[@]}"; do
    echo "$rec"
done
TOTAL_MB=$(awk "BEGIN {printf \"%.2f\", $TOTAL_BYTES / 1048576}")
TOTAL_GB=$(awk "BEGIN {printf \"%.3f\", $TOTAL_BYTES / 1073741824}")
echo "----------------------------------------------------------"
echo "Total pushed: ${TOTAL_MB} MB (${TOTAL_GB} GB, ${TOTAL_BYTES} bytes)"
echo "=========================================================="
echo ""
echo "Restarting app so it loads the new models..."
adb shell am force-stop org.ps3.sentinel
adb shell am start -n org.ps3.sentinel/.ui.HomeActivity
echo "App restarted so it loads the new models."
echo "Installation complete."
