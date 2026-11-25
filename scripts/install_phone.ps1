# scripts/install_phone.ps1
# Install PS3 Sentinel on an Android phone over adb from a folder of release assets.
#
# Usage:
#   .\scripts\install_phone.ps1 [[-Folder] <release_dir>]
# Default: ./release

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Folder = "./release"
)

# Continue, not Stop: adb writes progress to stderr, which Windows PowerShell 5.1 turns into
# a terminating error under Stop when output is redirected. Every adb call checks $LASTEXITCODE.
$ErrorActionPreference = "Continue"

Write-Host "=========================================================="
Write-Host "PS3 Sentinel: Android Phone Installation"
Write-Host "=========================================================="
Write-Host ""
Write-Host "Release assets can be downloaded via:"
Write-Host "  GitHub CLI: gh release download phase1-submission --repo Vishnu-3727/ps3-sentinel --dir $Folder"
Write-Host "  Browser:    https://github.com/Vishnu-3727/ps3-sentinel/releases/tag/phase1-submission"
Write-Host ""

# 1. Check adb and one connected device
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Error "adb command not found on PATH. Please ensure Android SDK platform-tools is installed and on PATH."
    exit 1
}

$devicesOutput = & adb devices
$connectedDevices = @()
foreach ($line in ($devicesOutput -split "`r?`n")) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("List of devices attached")) {
        continue
    }
    $parts = $trimmed -split "\s+"
    if ($parts.Count -ge 2 -and $parts[1] -eq "device") {
        $connectedDevices += $parts[0]
    }
}

if ($connectedDevices.Count -eq 0) {
    Write-Error "No connected Android device found via adb. Connect a device with USB debugging enabled."
    exit 1
}
if ($connectedDevices.Count -gt 1) {
    Write-Error ("Multiple devices connected (" + ($connectedDevices -join ", ") + "). Please connect only one device.")
    exit 1
}

$deviceSerial = $connectedDevices[0]
Write-Host ("Connected device: " + $deviceSerial)
Write-Host ""

# Resolve folder path
if (-not (Test-Path $Folder)) {
    Write-Error ("Release assets folder not found: " + $Folder)
    exit 1
}
$releaseDir = (Resolve-Path $Folder).Path

# 2. Verify assets against SHA256SUMS
$sumsPath = Join-Path $releaseDir "SHA256SUMS"
if (-not (Test-Path $sumsPath)) {
    Write-Error ("SHA256SUMS not found in " + $releaseDir)
    exit 1
}

$expectedHashes = @{}
foreach ($line in Get-Content $sumsPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    $parts = $trimmed -split "\s+", 2
    if ($parts.Count -eq 2) {
        $hashVal = $parts[0].Trim().ToLowerInvariant()
        $fileName = $parts[1].Trim().TrimStart("*").Trim()
        $expectedHashes[$fileName] = $hashVal
    }
}

function Verify-AssetFile {
    param([string]$Name)
    $targetPath = Join-Path $releaseDir $Name
    if (-not (Test-Path $targetPath)) {
        Write-Error ("Asset file missing: " + $Name + " in " + $releaseDir)
        exit 1
    }
    if (-not $expectedHashes.ContainsKey($Name)) {
        Write-Error ("Asset " + $Name + " not listed in SHA256SUMS")
        exit 1
    }
    $actualHash = (Get-FileHash -Path $targetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = $expectedHashes[$Name]
    if ($actualHash -ne $expectedHash) {
        Write-Error ("SHA256 mismatch for " + $Name + "!`nExpected: " + $expectedHash + "`nActual:   " + $actualHash)
        exit 1
    }
    Write-Host ("  [OK] " + $Name)
}

Write-Host "Verifying release assets against SHA256SUMS..."
$baseAssets = @(
    "ps3-sentinel-1.0.apk",
    "url_cnn_v2.pte",
    "vocab.json",
    "id_map.json",
    "sms_vocab.txt",
    "llama.pte",
    "tokenizer.model"
)

foreach ($asset in $baseAssets) {
    Verify-AssetFile -Name $asset
}

# Verify optional SMS model assets if present
foreach ($smsModel in @("sms_int8.pte", "sms_fp32.pte")) {
    $smsPath = Join-Path $releaseDir $smsModel
    if (Test-Path $smsPath) {
        Verify-AssetFile -Name $smsModel
    }
}
Write-Host "Asset integrity verification passed."
Write-Host ""

# 3. adb install -r the APK
$apkFile = Join-Path $releaseDir "ps3-sentinel-1.0.apk"
Write-Host ("Installing APK: " + $apkFile + "...")
& adb install -r $apkFile
if ($LASTEXITCODE -ne 0) {
    Write-Error ("adb install failed with exit code " + $LASTEXITCODE)
    exit 1
}
Write-Host "APK installed successfully."
Write-Host ""

# 4. Launch the app once so its folder exists
Write-Host "Launching app to initialize app data directories..."
& adb shell am start --user 0 -W -n org.ps3.sentinel/.ui.HomeActivity
Start-Sleep -Seconds 2

# 5. Read the Features line of /proc/cpuinfo
Write-Host "Checking CPU features from /proc/cpuinfo..."
$cpuInfoText = & adb shell cat /proc/cpuinfo
$featuresLine = $null
foreach ($line in ($cpuInfoText -split "`r?`n")) {
    if ($line -match "^\s*Features\s*:\s*(.*)$") {
        $featuresLine = $Matches[1].Trim()
        break
    }
}

$pushInt8 = $false
$pushFp32 = $false

if ($featuresLine) {
    Write-Host ("Detected Features: " + $featuresLine)
    if ($featuresLine -match "(^|\s)asimddp(\s|$)") {
        Write-Host "CPU has Arm dot product (asimddp): selecting sms_int8.pte"
        $pushInt8 = $true
    } else {
        Write-Host "CPU lacks Arm dot product (no asimddp): selecting sms_fp32.pte"
        $pushFp32 = $true
    }
} else {
    Write-Warning "Could not read Features line from /proc/cpuinfo; pushing both sms_int8.pte and sms_fp32.pte"
    $pushInt8 = $true
    $pushFp32 = $true
}

# 6. Push models to /sdcard/Android/data/org.ps3.sentinel/files/models/
$remoteModelsDir = "/sdcard/Android/data/org.ps3.sentinel/files/models/"
& adb shell mkdir -p $remoteModelsDir

$filesToPush = [System.Collections.Generic.List[string]]::new()
$filesToPush.Add("url_cnn_v2.pte")
$filesToPush.Add("vocab.json")
$filesToPush.Add("id_map.json")
$filesToPush.Add("sms_vocab.txt")
$filesToPush.Add("llama.pte")
$filesToPush.Add("tokenizer.model")

if ($pushInt8) {
    Verify-AssetFile -Name "sms_int8.pte"
    $filesToPush.Add("sms_int8.pte")
}
if ($pushFp32) {
    Verify-AssetFile -Name "sms_fp32.pte"
    $filesToPush.Add("sms_fp32.pte")
}

Write-Host ""
Write-Host "Pushing model files to device..."
$pushedRecords = @()
$totalBytes = 0

foreach ($fileName in $filesToPush) {
    $srcPath = Join-Path $releaseDir $fileName
    $item = Get-Item $srcPath
    $fileBytes = $item.Length
    $totalBytes += $fileBytes
    $remotePath = $remoteModelsDir + $fileName

    Write-Host ("  Pushing " + $fileName + " (" + [math]::Round($fileBytes / 1MB, 2) + " MB)...")
    & adb push $srcPath $remotePath
    if ($LASTEXITCODE -ne 0) {
        Write-Error ("adb push failed for " + $fileName)
        exit 1
    }

    $pushedRecords += [PSCustomObject]@{
        Name = $fileName
        Bytes = $fileBytes
        SizeMB = [math]::Round($fileBytes / 1MB, 2)
    }
}

# 7. Print what was pushed and the total size
Write-Host ""
Write-Host "=========================================================="
Write-Host "Summary of pushed files:"
Write-Host "=========================================================="
foreach ($rec in $pushedRecords) {
    Write-Host ("  - " + $rec.Name + ": " + $rec.SizeMB + " MB")
}
$totalMB = [math]::Round($totalBytes / 1MB, 2)
$totalGB = [math]::Round($totalBytes / 1GB, 3)
Write-Host "----------------------------------------------------------"
Write-Host ("Total pushed: " + $totalMB + " MB (" + $totalGB + " GB, " + $totalBytes + " bytes)")
Write-Host "=========================================================="
Write-Host ""
Write-Host "Restarting app so it loads the new models..."
& adb shell am force-stop org.ps3.sentinel
& adb shell am start -n org.ps3.sentinel/.ui.HomeActivity
Write-Host "App restarted so it loads the new models."
Write-Host "Installation complete."
