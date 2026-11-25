#!/usr/bin/env bash
# scripts/fetch_models.sh
# Download Linux CLI model assets from the phase1-submission GitHub release.
#
# Usage:
#   bash scripts/fetch_models.sh [models_directory]
# Default destination: ./models

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

MODELS_DIR="${1:-models}"
TAG="phase1-submission"
REPO="Vishnu-3727/ps3-sentinel"
BASE_URL="https://github.com/$REPO/releases/download/$TAG"

echo "=========================================================="
echo "PS3 Sentinel: Fetch Linux / Linux Models"
echo "=========================================================="
echo "Release:     $BASE_URL"
echo "Destination: $MODELS_DIR"
echo ""

mkdir -p "$MODELS_DIR/url_v2"
mkdir -p "$MODELS_DIR/sms_v6ml"
mkdir -p "$MODELS_DIR/llama32_1b"

HAS_GH=false
if command -v gh >/dev/null 2>&1; then
    HAS_GH=true
fi

download_asset() {
    local asset_name="$1"
    local destination_path="$2"
    local dest_dir
    dest_dir="$(dirname "$destination_path")"
    mkdir -p "$dest_dir"

    echo "Downloading $asset_name -> $destination_path..."
    local downloaded=false
    if [ "$HAS_GH" = true ]; then
        if gh release download "$TAG" --repo "$REPO" --pattern "$asset_name" --dir "$dest_dir" --clobber >/dev/null 2>&1; then
            local downloaded_file="$dest_dir/$asset_name"
            if [ "$downloaded_file" != "$destination_path" ] && [ -f "$downloaded_file" ]; then
                mv "$downloaded_file" "$destination_path"
            fi
            downloaded=true
        fi
    fi

    if [ "$downloaded" = false ]; then
        local url="$BASE_URL/$asset_name"
        if ! curl -sSL -f -o "$destination_path" "$url"; then
            echo "ERROR: Failed to download $url" >&2
            exit 1
        fi
    fi

    if [ ! -f "$destination_path" ]; then
        echo "ERROR: Destination file not found after download: $destination_path" >&2
        exit 1
    fi
}

# 1. Download SHA256SUMS
SUMS_FILE="$MODELS_DIR/SHA256SUMS"
download_asset "SHA256SUMS" "$SUMS_FILE"

sha256_verify() {
    local file_path="$1"
    local asset_name="$2"
    local expected_hash
    expected_hash=$(grep "[[:space:]]\*\{0,1\}$asset_name$" "$SUMS_FILE" | awk '{print $1}' | head -n1 | tr '[:upper:]' '[:lower:]')
    if [ -z "$expected_hash" ]; then
        echo "ERROR: Asset $asset_name not found in $SUMS_FILE" >&2
        exit 1
    fi

    local actual_hash
    if command -v sha256sum >/dev/null 2>&1; then
        actual_hash=$(sha256sum "$file_path" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    elif command -v shasum >/dev/null 2>&1; then
        actual_hash=$(shasum -a 256 "$file_path" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
    else
        echo "ERROR: Neither sha256sum nor shasum available for verification." >&2
        exit 1
    fi

    if [ "$actual_hash" != "$expected_hash" ]; then
        echo "ERROR: SHA256 mismatch for $asset_name!" >&2
        echo "  Expected: $expected_hash" >&2
        echo "  Actual:   $actual_hash" >&2
        exit 1
    fi
    echo "  [OK] $asset_name"
}

# 2. Download and verify Linux model assets
download_asset "url_cnn_v2.pte" "$MODELS_DIR/url_v2/url_cnn_v2.pte"
sha256_verify "$MODELS_DIR/url_v2/url_cnn_v2.pte" "url_cnn_v2.pte"

download_asset "vocab.json" "$MODELS_DIR/url_v2/vocab.json"
sha256_verify "$MODELS_DIR/url_v2/vocab.json" "vocab.json"

download_asset "sms_int8.pte" "$MODELS_DIR/sms_v6ml/sms_int8.pte"
sha256_verify "$MODELS_DIR/sms_v6ml/sms_int8.pte" "sms_int8.pte"

download_asset "id_map.json" "$MODELS_DIR/sms_v6ml/id_map.json"
sha256_verify "$MODELS_DIR/sms_v6ml/id_map.json" "id_map.json"

download_asset "llama.pte" "$MODELS_DIR/llama32_1b/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
sha256_verify "$MODELS_DIR/llama32_1b/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte" "llama.pte"

download_asset "tokenizer.model" "$MODELS_DIR/llama32_1b/tokenizer.model"
sha256_verify "$MODELS_DIR/llama32_1b/tokenizer.model" "tokenizer.model"

# 3. Download and extract sms_tokenizer.zip into models/sms_v6ml/tokenizer
TOKENIZER_ZIP="$MODELS_DIR/sms_v6ml/sms_tokenizer.zip"
download_asset "sms_tokenizer.zip" "$TOKENIZER_ZIP"
sha256_verify "$TOKENIZER_ZIP" "sms_tokenizer.zip"

TOK_DIR="$MODELS_DIR/sms_v6ml/tokenizer"
rm -rf "$TOK_DIR"
mkdir -p "$TOK_DIR"
echo "Unzipping sms_tokenizer.zip into $TOK_DIR..."
unzip -q -o "$TOKENIZER_ZIP" -d "$TOK_DIR"
rm -f "$TOKENIZER_ZIP"

echo "All Linux models downloaded and verified successfully."
