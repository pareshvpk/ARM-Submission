<#
.SYNOPSIS
    Single-phone device test for PS3 Sentinel (2026-11-08 protocol).

.DESCRIPTION
    Runs the per-phone protocol used for the reports in docs/device_tests/:
      1. Reads device information only (manufacturer, model, Android version,
         SoC, RAM, CPU Features, free space on /sdcard).
      2. Installs the APK with --user 0, launches it once with
         am start --user 0 -W, waits 3 s and force-stops it with
         am force-stop --user 0. The app must create
         /sdcard/Android/data/org.ps3.sentinel itself: on Android 14 (moto g73)
         an adb-created folder first makes the app report every model missing
         (DT-1). Only then are the models pushed.
      3. Pushes the seven model role files and models.sha256. sms_fp32.pte is
         pushed only when it exists locally and the phone does not report the
         asimddp (Arm dot product) feature in /proc/cpuinfo, or when -PushFp32
         is given; a dot-product phone gets any leftover copy removed instead.
         Every pushed file is verified with sha256sum on the phone against the
         local hash.
      4. Grants POST_NOTIFICATIONS only when ro.build.version.sdk >= 33
         (DT-10). All install, grant, list, start, force-stop and uninstall
         calls use --user 0 (DT-12).
      5. Cold-launches with am start --user 0 -W and waits for
         model_load_model=llama in the app's own logcat (logcat --pid).
      6. Sends the six messages from docs/device_tests/*.md through the share
         intent, reads the result with uiautomator dump to
         /data/local/tmp/ps3_ui.xml followed by cat, deletes that file right
         after reading it (also when the read fails), and saves screenshots
         with exec-out screencap.
      7. Records dumpsys meminfo, uninstalls with --user 0, and runs the
         leftover checks from the reports without dismissing anything else.
      8. Writes a Markdown report in the same format as the existing device
         reports.

    The script never changes phone settings, never clears logcat, and writes no
    file on the phone outside /sdcard/Android/data/org.ps3.sentinel except the
    UI dump /data/local/tmp/ps3_ui.xml, which is deleted right after it is read.

.PARAMETER Serial
    ADB device serial (no default; use -Serial, env ANDROID_SERIAL, or the
    single connected device).

.PARAMETER ApkPath
    Path to the Android debug APK.

.PARAMETER AdbPath
    Path to adb. Defaults to %LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
    or adb on PATH.

.PARAMETER OutDir
    Local results folder. Default: bench/results/device_<model>_<timestamp>.

.PARAMETER MessageTimeoutSec
    Per-message timeout while waiting for the UI result.

.PARAMETER ModelLoadTimeoutSec
    Timeout while waiting for model_load_model=llama after the cold launch.

.PARAMETER SmsFp32Path
    Path to the FP32 (or hybrid) SMS model file to push under the phone name
    sms_fp32.pte. Defaults to models/sms_v6ml/sms_fp32_int8emb.pte.

.PARAMETER PushFp32
    Push sms_fp32.pte even when the phone reports asimddp (Arm dot product) and
    therefore never loads it. By default the file is skipped on such phones.
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string]$Serial,

    [Parameter()]
    [string]$ApkPath = "android/app/build/outputs/apk/debug/app-debug.apk",

    [Parameter()]
    [string]$AdbPath = "",

    [Parameter()]
    [string]$OutDir = "",

    [Parameter()]
    [int]$MessageTimeoutSec = 180,

    [Parameter()]
    [int]$ModelLoadTimeoutSec = 180,

    [Parameter()]
    [string]$SmsFp32Path = "models/sms_v6ml/sms_fp32_int8emb.pte",

    [Parameter()]
    [switch]$PushFp32
)

if (-not $Serial) {
    $Serial = $env:ANDROID_SERIAL
}

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

if (-not $AdbPath) {
    $sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    if (Test-Path $sdkAdb) {
        $AdbPath = $sdkAdb
    } else {
        $adbCmd = Get-Command adb -ErrorAction SilentlyContinue
        if ($adbCmd) {
            $AdbPath = $adbCmd.Source
        } else {
            $AdbPath = "adb.exe"
        }
    }
}

if (-not $Serial) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $deviceLines = & $AdbPath devices 2>$null
    } catch {
        $deviceLines = @()
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $onlineSerials = @()
    foreach ($deviceLine in @($deviceLines)) {
        $deviceLine = ($deviceLine | Out-String).Trim()
        if ($deviceLine -match '^(?!\s*List)([^\s]+)\s+device$') {
            $onlineSerials += $Matches[1]
        }
    }
    if ($onlineSerials.Count -eq 1) {
        $Serial = $onlineSerials[0]
    }
}
if (-not $Serial) {
    Write-Error "No serial. Set ANDROID_SERIAL, pass -Serial, or connect one device."
    exit 1
}

$PackageName = "org.ps3.sentinel"
$MainActivity = "org.ps3.sentinel/.ui.MainActivity"
$DeviceModelDir = "/sdcard/Android/data/$PackageName/files/models"

$script:LastAdbExitCode = 0

function Invoke-Adb {
    param([string[]]$Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $allArgs = @("-s", $Serial) + $Arguments
        $output = & $AdbPath $allArgs 2>$null
        $script:LastAdbExitCode = $LASTEXITCODE
        $output
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Invoke-AdbShell {
    param([string]$Command)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $AdbPath -s $Serial shell $Command 2>$null
        $script:LastAdbExitCode = $LASTEXITCODE
        $output
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-DeviceProp {
    param([string]$Name)
    return ((Invoke-Adb @("shell", "getprop", $Name)) -join "`n").Trim()
}

function ConvertTo-ShellSingleQuoted {
    param([string]$Text)
    $escaped = $Text.Replace("'", "'\''")
    return "'" + $escaped + "'"
}

function Get-UiDumpText {
    # uiautomator dump to /dev/tty prints only "UI hierchary dumped to: /dev/tty"
    # on some builds (Samsung Galaxy M31, Android 12) and no XML, so dump to a
    # file in /data/local/tmp, read it, and always remove it afterwards.
    $remoteDumpPath = "/data/local/tmp/ps3_ui.xml"
    try {
        Invoke-Adb @("shell", "uiautomator", "dump", $remoteDumpPath) | Out-Null
        return ((Invoke-Adb @("shell", "cat", $remoteDumpPath)) -join "`n")
    } finally {
        Invoke-Adb @("shell", "rm", "-f", $remoteDumpPath) | Out-Null
    }
}

function ConvertFrom-UiDump {
    param([string]$Xml)
    $texts = @()
    foreach ($m in [regex]::Matches($Xml, 'text="([^"]*)"')) {
        $value = [System.Net.WebUtility]::HtmlDecode($m.Groups[1].Value)
        if ($value -ne "") { $texts += $value }
    }
    $joined = ($texts -join "`n")

    $riskLevel = ""
    $riskMatch = [regex]::Match($joined, 'HIGH RISK|SUSPICIOUS|LOOKS SAFE|NOT CHECKED|CHECKING|UNAVAILABLE')
    if ($riskMatch.Success) { $riskLevel = $riskMatch.Value }

    $evidence = ""
    foreach ($t in $texts) {
        if ($t -match '^(SCAM|HAM|SUSPICIOUS|SAFE)$') { $evidence = $t; break }
    }

    $adviceSource = ""
    foreach ($t in $texts) {
        if ($t -eq "Llama 3.2 1B (On-Device)" -or
            $t -eq "Heuristic Template (timeout)" -or
            $t -eq "Heuristic Template") {
            $adviceSource = $t
            break
        }
    }

    $riskScore = ""
    $m = [regex]::Match($joined, 'Risk:\s*([0-9.]+)\s*/\s*1\.00')
    if ($m.Success) { $riskScore = $m.Groups[1].Value }

    $detectMs = ""
    $smsMs = ""
    $m = [regex]::Match($joined, 'Detect:\s*([0-9.]+)\s*ms\s*\(SMS\s*([0-9.]+)')
    if ($m.Success) {
        $detectMs = $m.Groups[1].Value
        $smsMs = $m.Groups[2].Value
    }

    $adviceMs = ""
    $m = [regex]::Match($joined, 'Advice:\s*([0-9.]+)\s*ms')
    if ($m.Success) { $adviceMs = $m.Groups[1].Value }

    $ttftMs = ""
    $m = [regex]::Match($joined, 'TTFT:\s*([0-9]+)\s*ms')
    if ($m.Success) { $ttftMs = $m.Groups[1].Value }

    $decodeTps = ""
    $m = [regex]::Match($joined, 'Decode:\s*([0-9.]+)\s*tok/s')
    if ($m.Success) { $decodeTps = $m.Groups[1].Value }

    $totalMs = ""
    $m = [regex]::Match($joined, 'Total:\s*([0-9.]+)\s*ms')
    if ($m.Success) { $totalMs = $m.Groups[1].Value }

    return [PSCustomObject]@{
        Joined      = $joined
        Texts       = $texts
        RiskLevel   = $riskLevel
        Evidence    = $evidence
        RiskScore   = $riskScore
        DetectMs    = $detectMs
        SmsMs       = $smsMs
        AdviceMs    = $adviceMs
        TtftMs      = $ttftMs
        DecodeTps   = $decodeTps
        TotalMs     = $totalMs
        AdviceSource = $adviceSource
    }
}

function Find-NodeBounds {
    param([string]$Xml, [string]$ResourceId)
    $pattern = 'resource-id="[^"]*' + [regex]::Escape($ResourceId) + '"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
    $m = [regex]::Match($Xml, $pattern)
    if (-not $m.Success) { return $null }
    $x = [int](([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2)
    $y = [int](([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2)
    return @($x, $y)
}

function Save-ScreenCapture {
    param([string]$Path)
    $processArgs = @("-s", $Serial, "exec-out", "screencap", "-p")
    Start-Process -FilePath $AdbPath -ArgumentList $processArgs -RedirectStandardOutput $Path -NoNewWindow -Wait
    if (-not (Test-Path $Path)) {
        throw "screencap did not write $Path"
    }
}

function Get-LogMetric {
    param([string]$Text, [string]$Pattern)
    $m = [regex]::Match($Text, $Pattern)
    if ($m.Success) { return $m.Groups[1].Value }
    return ""
}

function Format-OrNone {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "not read" }
    return $Value
}

function Format-MarkdownCell {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    return ($Value -replace '\|', '\|')
}

# -----------------------------------------------------------------------------
# 1. Read-only device information
# -----------------------------------------------------------------------------
Write-Host "Reading device information (read-only)..." -ForegroundColor Yellow
$manufacturer = Get-DeviceProp "ro.product.manufacturer"
$model = Get-DeviceProp "ro.product.model"
$androidVersion = Get-DeviceProp "ro.build.version.release"
$sdkText = Get-DeviceProp "ro.build.version.sdk"
$socModel = Get-DeviceProp "ro.soc.model"
$board = Get-DeviceProp "ro.board.platform"
$hardware = Get-DeviceProp "ro.hardware"
$soc = $socModel
if (-not $soc) { $soc = $board }
if (-not $soc) { $soc = $hardware }

$cpuInfo = (Invoke-Adb @("shell", "cat", "/proc/cpuinfo")) -join "`n"
$cpuInfoReadOk = ($script:LastAdbExitCode -eq 0) -and ($cpuInfo.Trim() -ne "")
$cpuFeatures = ""
$featureMatches = [regex]::Matches($cpuInfo, 'Features\s*:\s*([^\r\n]+)')
if ($featureMatches.Count -gt 0) {
    $cpuFeatures = $featureMatches[0].Groups[1].Value.Trim()
}
$featuresReadOk = $cpuInfoReadOk -and ($featureMatches.Count -gt 0)

# Every core reports its own Features line, and asimddp (Arm dot product) can
# differ per core, so test each line rather than only the first one. A failed
# read leaves $hasAsimddp false, which keeps the safe old behaviour (push both).
$hasAsimddp = $false
foreach ($featureMatch in $featureMatches) {
    if ($featureMatch.Groups[1].Value -match '(^|\s)asimddp(\s|$)') {
        $hasAsimddp = $true
        break
    }
}

$memInfo = (Invoke-Adb @("shell", "cat", "/proc/meminfo")) -join "`n"
$memTotalKb = Get-LogMetric -Text $memInfo -Pattern 'MemTotal:\s*(\d+)\s*kB'
$memAvailableKb = Get-LogMetric -Text $memInfo -Pattern 'MemAvailable:\s*(\d+)\s*kB'
$ramGiB = ""
if ($memTotalKb) {
    $ramGiB = [string][math]::Round(([double]$memTotalKb / 1048576.0), 1)
}

$dfOut = @(Invoke-Adb @("shell", "df", "-h", "/sdcard") | Where-Object { $_.Trim() -ne "" })
$freeSpace = ""
if ($dfOut.Count -gt 0) { $freeSpace = $dfOut[$dfOut.Count - 1].Trim() }

$sdkLevel = 0
$sdkParsed = [int]::TryParse($sdkText, [ref]$sdkLevel)
$dateStamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$dateOnly = (Get-Date).ToString("yyyy-MM-dd")
$slug = (($manufacturer + "_" + $model) -replace '[^A-Za-z0-9]+', '_').Trim('_')
if (-not $slug) { $slug = "device" }

if (-not $OutDir) {
    $OutDir = Join-Path $RepoRoot "bench/results/device_${slug}_$dateStamp"
}
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  PS3 Sentinel: single-phone device test" -ForegroundColor White
Write-Host "  Device:  $manufacturer $model (Android $androidVersion, API $sdkText)" -ForegroundColor White
Write-Host "  Serial:  $Serial" -ForegroundColor White
Write-Host "  ADB:     $AdbPath" -ForegroundColor White
Write-Host "  APK:     $ApkPath" -ForegroundColor White
Write-Host "  Out:     $OutDir" -ForegroundColor White
Write-Host "================================================================================" -ForegroundColor Cyan

@(
    "manufacturer=$manufacturer",
    "model=$model",
    "android_version=$androidVersion",
    "sdk=$sdkText",
    "soc=$soc",
    "ram_gib=$ramGiB",
    "mem_total_kb=$memTotalKb",
    "cpu_features=$cpuFeatures",
    "free_space=$freeSpace"
) | Out-File -FilePath (Join-Path $OutDir "device_info.txt") -Encoding utf8

# -----------------------------------------------------------------------------
# 2. Install and first launch before any adb-created folder (DT-1, DT-12)
# -----------------------------------------------------------------------------
Write-Host "`n[1/8] Installing APK (--user 0)..." -ForegroundColor Yellow
if (-not (Test-Path $ApkPath)) {
    Write-Error "APK not found: $ApkPath"
    exit 1
}
$installOut = (Invoke-Adb @("install", "--user", "0", "-r", "-d", $ApkPath)) -join "`n"
$installOk = ($installOut -match 'Success')
if (-not $installOk) {
    Write-Warning "adb install did not report Success: $installOut"
}

Write-Host "`n[2/8] First launch, wait 3 s, force-stop (app must create its own folder)..." -ForegroundColor Yellow
Invoke-Adb @("shell", "am", "start", "--user", "0", "-W", "-n", $MainActivity) | Out-Null
Start-Sleep -Seconds 3
Invoke-Adb @("shell", "am", "force-stop", "--user", "0", $PackageName) | Out-Null

# -----------------------------------------------------------------------------
# 3. Push and verify models
# -----------------------------------------------------------------------------
Write-Host "`n[3/8] Pushing models to $DeviceModelDir..." -ForegroundColor Yellow
Invoke-AdbShell "mkdir -p '$DeviceModelDir'" | Out-Null

if ([System.IO.Path]::IsPathRooted($SmsFp32Path)) {
    $smsFp32Local = $SmsFp32Path
} else {
    $smsFp32Local = Join-Path $RepoRoot $SmsFp32Path
}

if (-not $featuresReadOk) {
    $pushSmsInt8 = $true
    $pushSmsFp32 = $true
} elseif ($hasAsimddp) {
    $pushSmsInt8 = $true
    $pushSmsFp32 = [bool]$PushFp32
} else {
    if (Test-Path $smsFp32Local) {
        $pushSmsInt8 = $false
        $pushSmsFp32 = $true
    } else {
        Write-Warning "Phone lacks Arm dot product (asimddp) but SmsFp32Path does not exist locally ($smsFp32Local); pushing sms_int8.pte fallback instead of leaving the phone with no SMS model."
        $pushSmsInt8 = $true
        $pushSmsFp32 = $false
    }
}

$modelFilesPath = Join-Path $RepoRoot "sentinel/data/model_files.json"
if (-not (Test-Path $modelFilesPath)) {
    throw "Model files manifest not found: $modelFilesPath"
}
$modelFiles = Get-Content -Raw -Path $modelFilesPath | ConvertFrom-Json
$roleToLocal = @{
    url_model = "models/url_v2/url_cnn_v2.pte"
    url_vocab = "models/url_v2/vocab.json"
    sms_id_map = "models/sms_v6ml/id_map.json"
    sms_vocab = "models/sms_v6ml/sms_vocab.txt"
    llama_model = "models/llama32_et_community/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
    llama_tokenizer = "models/llama32_et_community/tokenizer.model"
}
if ($pushSmsInt8) {
    $roleToLocal["sms_model"] = "models/sms_v6ml/sms_int8.pte"
}

$modelsToPush = @()
foreach ($role in $roleToLocal.Keys) {
    $entry = $modelFiles.files.$role
    $modelsToPush += [PSCustomObject]@{
        Role       = $role
        Local      = $roleToLocal[$role]
        RemoteName = $entry.phone
    }
}
$modelsToPush = $modelsToPush | Sort-Object -Property Role

$pushedFiles = @()
foreach ($m in $modelsToPush) {
    $srcPath = Join-Path $RepoRoot $m.Local
    if (-not (Test-Path $srcPath)) {
        throw "Model file missing locally: $srcPath"
    }
    $remotePath = "$DeviceModelDir/$($m.RemoteName)"
    Write-Host "  Pushing $($m.RemoteName)..." -ForegroundColor Green
    Invoke-Adb @("push", $srcPath, $remotePath) | Out-Null
    $pushedFiles += [PSCustomObject]@{ Local = $srcPath; Remote = $remotePath; Name = $m.RemoteName }
}

$smsInt8Remote = "$DeviceModelDir/sms_int8.pte"
if (-not $pushSmsInt8) {
    Write-Host "  Skipping sms_int8.pte: phone does not have the Arm dot-product feature, so the app uses sms_fp32 only; removed any leftover from older pushes." -ForegroundColor DarkGray
    Invoke-AdbShell "rm -f '$smsInt8Remote'" | Out-Null
}

$smsFp32Remote = "$DeviceModelDir/sms_fp32.pte"

if (-not $pushSmsFp32) {
    if ($hasAsimddp) {
        Write-Host "  Skipping sms_fp32.pte: phone has the Arm dot-product feature, so the app uses sms_int8 only; removed any leftover from older pushes." -ForegroundColor DarkGray
    } else {
        Write-Host "  Skipping sms_fp32.pte: file not present locally; removed any leftover from older pushes." -ForegroundColor DarkGray
    }
    Invoke-AdbShell "rm -f '$smsFp32Remote'" | Out-Null
} elseif (Test-Path $smsFp32Local) {
    Write-Host "  Pushing sms_fp32.pte (optional, phones without dot product)..." -ForegroundColor Green
    Invoke-Adb @("push", $smsFp32Local, $smsFp32Remote) | Out-Null
    $pushedFiles += [PSCustomObject]@{ Local = $smsFp32Local; Remote = $smsFp32Remote; Name = "sms_fp32.pte" }
} else {
    Write-Host "  sms_fp32.pte not present locally ($smsFp32Local); skipping optional file." -ForegroundColor DarkGray
}

$manifestOut = Join-Path $OutDir "models.sha256"
$venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) { $py = $venvPy } else { $py = "python" }
$manifestScript = Join-Path $RepoRoot "deploy/android/write_models_manifest.py"
$roleArgs = @("--model-files", $modelFilesPath, "--out", $manifestOut)
foreach ($m in $modelsToPush) {
    $roleArgs += @("--role", "$($m.Role)=$($m.Local)")
}
# Optional sms_fp32.pte (phones without dot product): include it in the
# models.sha256 manifest when present locally, matching full_test.ps1.
if ($pushSmsFp32 -and (Test-Path $smsFp32Local)) {
    $roleArgs += @("--role", "sms_fp32=$smsFp32Local")
}
Write-Host "  Generating $manifestOut..." -ForegroundColor Green
& $py $manifestScript @roleArgs
if ($LASTEXITCODE -ne 0) {
    throw "write_models_manifest.py failed"
}
Invoke-Adb @("push", $manifestOut, "$DeviceModelDir/models.sha256") | Out-Null
$pushedFiles += [PSCustomObject]@{
    Local = $manifestOut
    Remote = "$DeviceModelDir/models.sha256"
    Name = "models.sha256"
}

Write-Host "  Verifying every pushed file with sha256sum on the phone..." -ForegroundColor Yellow
foreach ($f in $pushedFiles) {
    $localHash = (Get-FileHash -LiteralPath $f.Local -Algorithm SHA256).Hash.ToLower()
    $remoteLine = ((Invoke-AdbShell "sha256sum '$($f.Remote)'") -join "`n").Trim()
    $remoteHash = ""
    if ($remoteLine) { $remoteHash = (($remoteLine -split '\s+')[0]).ToLower() }
    if ($remoteHash -ne $localHash) {
        throw "SHA-256 mismatch for $($f.Name): local $localHash != phone $remoteHash"
    }
    Write-Host "    Verified $($f.Name) $($localHash.Substring(0, 12))..." -ForegroundColor Green
}

$deviceListing = (Invoke-AdbShell "ls -lh '$DeviceModelDir'") -join "`n"
$deviceListing | Out-File -FilePath (Join-Path $OutDir "models_on_phone.txt") -Encoding utf8

# -----------------------------------------------------------------------------
# 4. Runtime permissions (DT-10, DT-12)
# -----------------------------------------------------------------------------
Write-Host "`n[4/8] Granting runtime permissions (--user 0)..." -ForegroundColor Yellow
$permissionNotes = @()
Invoke-Adb @("shell", "pm", "grant", "--user", "0", $PackageName, "android.permission.RECEIVE_SMS") | Out-Null
if ($script:LastAdbExitCode -eq 0) {
    $permissionNotes += "RECEIVE_SMS granted"
} else {
    $permissionNotes += "RECEIVE_SMS grant failed"
}
if (-not $sdkParsed) {
    $permissionNotes += "POST_NOTIFICATIONS skipped (could not read API level)"
} elseif ($sdkLevel -ge 33) {
    Invoke-Adb @("shell", "pm", "grant", "--user", "0", $PackageName, "android.permission.POST_NOTIFICATIONS") | Out-Null
    if ($script:LastAdbExitCode -eq 0) {
        $permissionNotes += "POST_NOTIFICATIONS granted (API $sdkLevel)"
    } else {
        $permissionNotes += "POST_NOTIFICATIONS grant failed (API $sdkLevel)"
    }
} else {
    $permissionNotes += "POST_NOTIFICATIONS skipped on API $sdkLevel (< 33)"
}
Write-Host "  $($permissionNotes -join '; ')" -ForegroundColor DarkGray

# -----------------------------------------------------------------------------
# 5. Cold launch and wait for model_load_model=llama (app logcat --pid)
# -----------------------------------------------------------------------------
Write-Host "`n[5/8] Cold launch and wait for the Llama model load..." -ForegroundColor Yellow
Invoke-Adb @("shell", "am", "force-stop", "--user", "0", $PackageName) | Out-Null
$startOut = (Invoke-Adb @("shell", "am", "start", "--user", "0", "-W", "-n", $MainActivity)) -join "`n"
$coldStartMs = Get-LogMetric -Text $startOut -Pattern 'TotalTime:\s*(\d+)'

$appPid = ""
$pidElapsed = 0
while ($pidElapsed -lt 15 -and -not $appPid) {
    Start-Sleep -Seconds 1
    $pidElapsed += 1
    $appPid = ((Invoke-Adb @("shell", "pidof", $PackageName)) -join " ").Trim()
}
# pidof can return several pids on multi-pid devices; logcat --pid takes one.
$appPid = ($appPid -split '\s+' | Where-Object { $_ } | Select-Object -First 1)
if (-not $appPid) {
    throw "The app process was not found after launch."
}

$modelLog = ""
$modelElapsed = 0
$modelLoadReady = $false
while ($modelElapsed -lt $ModelLoadTimeoutSec) {
    Start-Sleep -Seconds 2
    $modelElapsed += 2
    $modelLog = ((Invoke-Adb @("logcat", "-d", "--pid=$appPid", "-s", "PS3Timing:V")) -join "`n")
    if ($modelLog -match 'model_load_model=llama') {
        $modelLoadReady = $true
        break
    }
}
$modelLog | Out-File -FilePath (Join-Path $OutDir "logcat_ps3timing_coldlaunch.txt") -Encoding utf8
if (-not $modelLoadReady) {
    Write-Warning "model_load_model=llama was not seen within ${ModelLoadTimeoutSec}s; continuing so the report records it."
}

# Dismiss only the app's own onboarding overlay, which otherwise covers the results.
# No system dialog and no phone setting is touched.
Start-Sleep -Seconds 1
$onboardingDump = Get-UiDumpText
$tapPoint = Find-NodeBounds -Xml $onboardingDump -ResourceId "btnNotNow"
if ($null -ne $tapPoint) {
    Write-Host "  Dismissing the app onboarding overlay (Not now)..." -ForegroundColor DarkGray
    Invoke-Adb @("shell", "input", "tap", "$($tapPoint[0])", "$($tapPoint[1])") | Out-Null
    Start-Sleep -Seconds 1
}

# -----------------------------------------------------------------------------
# 6. Six messages through the share intent, read with uiautomator dump to a file
# -----------------------------------------------------------------------------
Write-Host "`n[6/8] Sending six test messages through the share intent..." -ForegroundColor Yellow
$messages = @(
    [PSCustomObject]@{
        Label  = "SBI KYC"
        Marker = "sbi-kyc-update.xyz"
        Text   = "Dear customer your SBI account KYC is pending, account will be blocked today. Update now: http://sbi-kyc-update.xyz/login"
    },
    [PSCustomObject]@{
        Label  = "Hinglish Axis card KYC"
        Marker = "axis-kyc.top"
        Text   = "Namaste! Aapka Axis Bank credit card ka KYC pending hai. Aaj hi update karein: http://axis-kyc.top/update warna card block ho jayega."
    },
    [PSCustomObject]@{
        Label  = "Hinglish UPI refund PIN"
        Marker = "UPI refund"
        Text   = "Aapko UPI refund mila hai. Refund claim karne ke liye apna UPI PIN daalein: http://upi-refund-claim.top"
    },
    [PSCustomObject]@{
        Label  = "Instant loan .apk link"
        Marker = "app.apk"
        Text   = "Instant loan approved! Rs 50,000 in 5 minutes. Download the app now: http://quick-loan-cash.top/app.apk"
    },
    [PSCustomObject]@{
        Label  = "Shoe-store promotion"
        Marker = "shoe-store"
        Text   = "Big shoe-store sale! Flat 70 percent off on all footwear today only. Shop now: http://shoe-store-deals.top"
    },
    [PSCustomObject]@{
        Label  = "Order delivered"
        Marker = "order has been delivered"
        Text   = "Your order has been delivered. Thank you for shopping with us."
    }
)

$messageRows = @()
$msgIndex = 0
foreach ($msg in $messages) {
    $msgIndex++
    Write-Host "  -> Message ${msgIndex}: $($msg.Label)" -ForegroundColor White
    $quoted = ConvertTo-ShellSingleQuoted -Text $msg.Text
    $inner = "am start --user 0 -a android.intent.action.SEND -t text/plain " +
        "--es android.intent.extra.TEXT $quoted -n $MainActivity"
    Invoke-AdbShell $inner | Out-Null

    $deadline = (Get-Date).AddSeconds($MessageTimeoutSec)
    $lastDump = ""
    $parsed = $null
    $done = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $lastDump = Get-UiDumpText
        if ([string]::IsNullOrWhiteSpace($lastDump)) { continue }
        $parsed = ConvertFrom-UiDump -Xml $lastDump
        if ($parsed.RiskLevel -ne "" -and
            $parsed.RiskLevel -ne "CHECKING" -and
            $parsed.RiskLevel -ne "NOT CHECKED" -and
            $parsed.Joined -match [regex]::Escape($msg.Marker) -and
            $parsed.Joined -match 'Advice:') {
            $done = $true
            break
        }
    }

    if ($null -eq $parsed) { $parsed = ConvertFrom-UiDump -Xml $lastDump }
    $lastDump | Out-File -FilePath (Join-Path $OutDir "message_${msgIndex}_ui.xml") -Encoding utf8
    try {
        Save-ScreenCapture -Path (Join-Path $OutDir "message_${msgIndex}.png")
    } catch {
        Write-Warning "Screenshot $msgIndex failed: $_"
    }

    if (-not $done) {
        Write-Warning "Message $msgIndex did not finish within ${MessageTimeoutSec}s."
    } else {
        Write-Host "     $($parsed.RiskLevel) risk $($parsed.RiskScore), detect $($parsed.DetectMs) ms (SMS $($parsed.SmsMs) ms)" -ForegroundColor Green
    }

    $verdict = $parsed.RiskLevel
    if ($parsed.Evidence) {
        $verdict = $parsed.RiskLevel + ", " + $parsed.Evidence.ToLower()
    }
    $messageRows += [PSCustomObject]@{
        Index        = $msgIndex
        Label        = $msg.Label
        Done         = $done
        Verdict      = $verdict
        Risk         = $parsed.RiskScore
        DetectMs     = $parsed.DetectMs
        SmsMs        = $parsed.SmsMs
        TtftMs       = $parsed.TtftMs
        DecodeTps    = $parsed.DecodeTps
        AdviceMs     = $parsed.AdviceMs
        AdviceSource = $parsed.AdviceSource
    }
}

# -----------------------------------------------------------------------------
# 7. Memory, app logcat, uninstall and leftover checks
# -----------------------------------------------------------------------------
Write-Host "`n[7/8] Reading dumpsys meminfo and uninstalling..." -ForegroundColor Yellow
$memInfoDump = (Invoke-Adb @("shell", "dumpsys", "meminfo", $PackageName)) -join "`n"
$memInfoDump | Out-File -FilePath (Join-Path $OutDir "dumpsys_meminfo.txt") -Encoding utf8
$appLog = (Invoke-Adb @("logcat", "-d", "--pid=$appPid")) -join "`n"
$appLog | Out-File -FilePath (Join-Path $OutDir "logcat_app.txt") -Encoding utf8

$totalPss = Get-LogMetric -Text $memInfoDump -Pattern 'TOTAL PSS:\s*(\d+)'
$totalRss = Get-LogMetric -Text $memInfoDump -Pattern 'TOTAL RSS:\s*(\d+)'
$swapPss = Get-LogMetric -Text $memInfoDump -Pattern 'TOTAL SWAP PSS:\s*(\d+)'

$uninstallOut = (Invoke-Adb @("uninstall", "--user", "0", $PackageName)) -join "`n"
$uninstallOk = ($uninstallOut -match 'Success')
if (-not $uninstallOk) {
    Write-Warning "adb uninstall did not report Success: $uninstallOut"
}

Write-Host "`n[8/8] Running leftover checks..." -ForegroundColor Yellow
$leftoverRows = @()

$packageList = (Invoke-Adb @("shell", "pm", "list", "packages", "--user", "0", $PackageName)) -join "`n"
$packageAbsent = ($packageList -notmatch [regex]::Escape($PackageName))
$leftoverRows += [PSCustomObject]@{
    Check  = "package $PackageName (user 0)"
    Absent = $packageAbsent
    Detail = ($packageList -replace '\s+', ' ').Trim()
}

$pathsToCheck = @(
    "/sdcard/Android/data/$PackageName",
    "/sdcard/Android/media/$PackageName",
    "/sdcard/Android/obb/$PackageName",
    "/sdcard/ps3_offline",
    "/data/local/tmp/ps3_offline",
    "/data/local/tmp/ps3_ui.xml"
)
foreach ($path in $pathsToCheck) {
    $listing = ((Invoke-AdbShell "ls -d '$path'") -join "`n").Trim()
    $exists = ($script:LastAdbExitCode -eq 0) -and
        ($listing -ne "") -and
        ($listing -notmatch 'No such file|not found|Permission denied')
    $leftoverRows += [PSCustomObject]@{
        Check  = $path
        Absent = (-not $exists)
        Detail = $listing
    }
}

$sdcardList = ((Invoke-AdbShell "ls '/sdcard'") -join "`n")
$sdcardLeftovers = @($sdcardList -split "`r?`n" | Where-Object {
    $_.Trim() -ne "" -and ($_ -match '^msg_' -or $_ -eq 'window_dump.xml')
})
$leftoverRows += [PSCustomObject]@{
    Check  = "/sdcard/msg_* and /sdcard/window_dump.xml"
    Absent = ($sdcardLeftovers.Count -eq 0)
    Detail = ($sdcardLeftovers -join ", ")
}

$notificationDump = ((Invoke-Adb @("shell", "dumpsys", "notification")) -join "`n")
$notificationPresent = [regex]::IsMatch(
    $notificationDump,
    ('NotificationRecord[^\r\n]*' + [regex]::Escape($PackageName))
)
$leftoverRows += [PSCustomObject]@{
    Check  = "notification from $PackageName"
    Absent = (-not $notificationPresent)
    Detail = ""
}

$leftoversOk = $true
foreach ($row in $leftoverRows) {
    if (-not $row.Absent) { $leftoversOk = $false }
}

# -----------------------------------------------------------------------------
# 8. Markdown report
# -----------------------------------------------------------------------------
function Report-SectionValue {
    param([string]$Value)
    return (Format-MarkdownCell (Format-OrNone $Value))
}

$integrityUrl = Get-LogMetric -Text $modelLog -Pattern 'integrity_verify_model=url ms=([0-9.]+)'
$integritySms = Get-LogMetric -Text $modelLog -Pattern 'integrity_verify_model=sms ms=([0-9.]+)'
$integrityLlama = Get-LogMetric -Text $modelLog -Pattern 'integrity_verify_model=llama ms=([0-9.]+)'
$loadUrl = Get-LogMetric -Text $modelLog -Pattern 'model_load_model=url ms=([0-9.]+)'
$loadSms = Get-LogMetric -Text $modelLog -Pattern 'model_load_model=sms ms=([0-9.]+)'
$loadLlama = Get-LogMetric -Text $modelLog -Pattern 'model_load_model=llama ms=([0-9.]+)'

$coldStartText = "not read"
if ($coldStartMs) {
    $coldStartText = ([string][math]::Round(([double]$coldStartMs / 1000.0), 2)) + " s"
}
$integrityText = "url $integrityUrl ms, sms $integritySms ms, llama $integrityLlama ms"
if (-not $integrityUrl -and -not $integritySms -and -not $integrityLlama) {
    $integrityText = "not read"
}
$modelLoadText = "url $loadUrl ms, sms $loadSms ms, llama $loadLlama ms"
if (-not $loadUrl -and -not $loadSms -and -not $loadLlama) {
    $modelLoadText = "not read"
}
$memoryText = "TOTAL PSS $totalPss kB, TOTAL RSS $totalRss kB, swap PSS $swapPss kB"
if ($memAvailableKb) { $memoryText += ", MemAvailable $memAvailableKb kB" }
if (-not $totalPss -and -not $totalRss) {
    $memoryText = "not read"
}

$leftoverText = "all absent"
if (-not $leftoversOk) {
    $failed = @($leftoverRows | Where-Object { -not $_.Absent } | ForEach-Object { $_.Check })
    $leftoverText = "present: " + ($failed -join ", ")
}

$reportPath = Join-Path $OutDir ("device_report_" + $slug + "_" + (Get-Date).ToString("yyyyMMdd") + ".md")
$ramText = "unknown"
if ($ramGiB) { $ramText = "$ramGiB GiB" }
$report = @()
$report += "# Device test: $manufacturer $model ($dateOnly)"
$report += ""
$report += "Device: $manufacturer $model ($(Format-OrNone $soc)), $ramText RAM (MemTotal $(Format-OrNone $memTotalKb) kB), Android $(Format-OrNone $androidVersion) (API $(Format-OrNone $sdkText))."
$report += "CPU features: $(Format-OrNone $cpuFeatures). Free space on /sdcard: $(Format-OrNone $freeSpace)."
$report += "Serial $Serial, APK $ApkPath, test at $dateStamp. Install: $(if ($installOk) { 'Success' } else { 'see warning in the console log' })."
$report += ""
$report += "Scope rule: only ``$PackageName`` was installed, launched, granted permissions and read; no phone setting, other app or"
$report += "file was changed. Messages went in through the app's share intent; UI text was read with ``uiautomator dump`` to"
$report += "``/data/local/tmp/ps3_ui.xml`` and ``cat``, and that file was deleted right after every read. Screenshots were saved"
$report += "with ``exec-out screencap`` without writing files on the phone. At the end the app was"
$report += "uninstalled with ``--user 0`` and the leftover checks below ran without dismissing anything else."
$report += ""
$report += "## Results"
$report += ""
$report += "| Measure | Value |"
$report += "|---|---|"
$report += "| Install (``adb install --user 0``) | $(if ($installOk) { 'Success' } else { 'Failed; see console log' }) |"
$report += "| Permissions | $($permissionNotes -join '; ') |"
$report += "| Cold start (``am start -W`` TotalTime) | $coldStartText |"
$report += "| Cold launch after model push: integrity check | $integrityText |"
$report += "| Model load | $modelLoadText |"
$report += "| Memory with all models loaded | $memoryText |"
$report += "| Free space on /sdcard | $freeSpace |"
$report += "| Leftover checks after uninstall | $leftoverText |"
$report += ""
$report += "## Messages"
$report += ""
$report += "| # | Message | Verdict | Risk | Detect (SMS) | Llama TTFT | Decode | Advice | Advice source |"
$report += "|---|---|---|---|---|---|---|---|---|"
foreach ($row in $messageRows) {
    $detect = Report-SectionValue $row.DetectMs
    if ($row.DetectMs -or $row.SmsMs) {
        $detect = "$($row.DetectMs) ms ($($row.SmsMs))"
    }
    $ttft = "none"
    if ($row.TtftMs) { $ttft = "$($row.TtftMs) ms" }
    $decode = "none"
    if ($row.DecodeTps) { $decode = "$($row.DecodeTps) tok/s" }
    $advice = Report-SectionValue $row.AdviceMs
    if ($row.AdviceMs) { $advice = "$($row.AdviceMs) ms" }
    $source = Report-SectionValue $row.AdviceSource
    $verdict = Report-SectionValue $row.Verdict
    $risk = Report-SectionValue $row.Risk
    $report += "| $($row.Index) | $($row.Label) | $verdict | $risk | $detect | $ttft | $decode | $advice | $source |"
}
$report += ""
$report += "## Findings"
$report += ""
$finished = @($messageRows | Where-Object { $_.Done }).Count
$report += "- Messages analysed: $finished of $($messages.Count)."
if ($finished -lt $messages.Count) {
    $incomplete = @($messageRows | Where-Object { -not $_.Done } | ForEach-Object { $_.Index })
    $report += "- Did not finish within ${MessageTimeoutSec}s: message(s) $($incomplete -join ', ')."
}
if (-not $modelLoadReady) {
    $report += "- ``model_load_model=llama`` was not seen within ${ModelLoadTimeoutSec}s of the cold launch."
}
$report += "- Leftover checks after uninstall: $leftoverText."
$report += "- Permissions: $($permissionNotes -join '; ')."
$report += "- No phone setting was changed, logcat was not cleared, and no file was left on the phone: the only file written outside ``/sdcard/Android/data/$PackageName`` is the UI dump ``/data/local/tmp/ps3_ui.xml``, which was deleted right after each read."
$report += ""
$report -join "`n" | Out-File -FilePath $reportPath -Encoding utf8

Write-Host ""
Write-Host "Report: $reportPath" -ForegroundColor Green
Write-Host "Results: $OutDir" -ForegroundColor Green
if (-not $leftoversOk) {
    Write-Warning "Leftover checks found items that should be absent: $leftoverText"
}
if (-not $installOk -or -not $uninstallOk) {
    exit 1
}
