<#
.SYNOPSIS
    One-Command Android Hardware Test Kit (Samsung Galaxy F14).

.DESCRIPTION
    Automates end-to-end Phase 1 evaluation on Samsung Galaxy F14:
      1. Installs the debug APK (adb install --user 0).
      2. Launches the app once with am start --user 0 -W, waits 3 s, then stops it with
         am force-stop --user 0. The app's own first launch must create
         /sdcard/Android/data/org.ps3.sentinel before adb creates any folder there (DT-1):
         if adb creates the folder first, Android 14 on the moto g73 denies the app
         access and every model is reported missing. Only after the force-stop is the
         models folder created and models pushed.
      3. Pushes model role files and models.sha256. On phones without asimddp
         (Arm dot product), sms_int8.pte is skipped (and any leftover copy
         removed) and sms_fp32.pte is pushed instead. On dot-product phones,
         sms_fp32.pte is skipped (and any leftover copy removed) unless
         -PushFp32 is given. If the CPU Features line cannot be read, both are
         pushed. Then generates models.sha256 with write_models_manifest.py and
         pushes it so the integrity check is active. Every pushed file is
         verified with sha256sum on the phone against the local Get-FileHash value.
      4. Grants POST_NOTIFICATIONS only when the phone API level (getprop ro.build.version.sdk)
         is 33 or higher (DT-10; the permission does not exist below API 33). Relaunches the
         app with --user 0.
      5. Enables Airplane Mode.
      6. Records on-device MP4 video per message (msg_1.mp4 ... msg_N.mp4) with screenrecord.
      7. Inputs and analyses demo threat messages loaded from bench/bench_messages.txt, polling PS3Llama stats.
      8. Captures on-device PNG screenshots per message (pulled afterwards to avoid PowerShell piping corruption).
      9. In a FINALLY block, restores connectivity (airplane mode disabled).
     10. Saves logcat lines for tags PS3Llama and PS3Sms plus dumpsys meminfo org.ps3.sentinel.

.PARAMETER Serial
    ADB device serial number (no default; use -Serial, env ANDROID_SERIAL, or the single connected device).

.PARAMETER ApkPath
    Path to the Android debug APK (default: android/app/build/outputs/apk/debug/app-debug.apk).

.PARAMETER AdbPath
    Path to adb executable. Defaults to $env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe or PATH.

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
    [int]$TapX = 540,

    [Parameter()]
    [int]$TapMessageY = 500,

    [Parameter()]
    [int]$TapAnalyseY = 740,

    [Parameter()]
    [string]$SmsFp32Path = "models/sms_v6ml/sms_fp32_int8emb.pte",

    [Parameter()]
    [switch]$PushFp32
)

# Resolve the ADB serial: explicit parameter wins, then environment variable ANDROID_SERIAL.
# No hard-coded default — if neither is set, the single connected device is used
# (resolved below once $AdbPath is known).
if (-not $Serial) {
    $Serial = $env:ANDROID_SERIAL
}

# Tap coordinates: attempt uiautomator-based view lookup by resource id where simple;
# otherwise these fixed coordinates are parameters ($TapX, $TapMessageY, $TapAnalyseY) and
# must be retuned for each screen size — they are not guaranteed to hit the message box or
# Analyse button on other phones.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

# Resolve ADB path
if (-not $AdbPath) {
    $sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    if (Test-Path $sdkAdb) {
        $AdbPath = $sdkAdb
    } else {
        $cmd = Get-Command adb -ErrorAction SilentlyContinue
        if ($cmd) {
            $AdbPath = $cmd.Source
        } else {
            $AdbPath = "adb.exe"
        }
    }
}

# Single-device fallback when neither -Serial nor ANDROID_SERIAL was given.
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
    Write-Error "ANDROID_SERIAL is not set and -Serial was not provided, and no single connected device was found. Set ANDROID_SERIAL (e.g. <adb-serial>), pass -Serial, or connect one device."
    exit 1
}

$PackageName = "org.ps3.sentinel"
$MainActivity = "org.ps3.sentinel/.ui.MainActivity"
$DeviceModelDir = "/sdcard/Android/data/$PackageName/files/models"

$DateStamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$OutDir = Join-Path $RepoRoot "bench/results/f14_$DateStamp"
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  PS3 Sentinel: Full Phase 1 Android Test Kit (Samsung F14)" -ForegroundColor White
Write-Host "  Serial:       $Serial" -ForegroundColor White
Write-Host "  ADB:          $AdbPath" -ForegroundColor White
Write-Host "  APK:          $ApkPath" -ForegroundColor White
Write-Host "  Out Directory:$OutDir" -ForegroundColor White
Write-Host "================================================================================" -ForegroundColor Cyan

function Invoke-Adb {
    param([string[]]$Arguments)
    # Windows PowerShell 5.1 promotes every native-program stderr line to an error
    # record; with the script-level $ErrorActionPreference = Stop that becomes
    # terminating, so a stray adb/pkill warning would abort the caller instead of
    # just failing that adb command. Run locally with Continue and suppressed
    # stderr; callers that need success check $LASTEXITCODE (the native exit code).
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $allArgs = @("-s", $Serial) + $Arguments
        $output = & $AdbPath $allArgs 2>$null
        $output
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

# Phone-local "MM-DD HH:MM:SS.mmm" for logcat -T, or $null when unavailable.
# Logcat is never cleared (C-11): clearing wipes every app's logs on the
# phone. Instead each read uses logcat -T from a start time recorded here,
# so only this run's (and this message's) app lines are read.
function Get-PhoneLogTime {
    $raw = (Invoke-Adb @("shell", "date '+%m-%d %H:%M:%S.000'") -join "`n")
    $found = [regex]::Matches($raw, '\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}')
    if ($found.Count -gt 0) { return $found[$found.Count - 1].Value }
    return $null
}

# Centre of a view by resource id (activity_main.xml), falling back to the
# fixed coordinates when the uiautomator lookup fails. Prints which was used.
function Resolve-Tap {
    param([string]$ResourceId, [int]$FallbackX, [int]$FallbackY)
    $x = $FallbackX; $y = $FallbackY; $how = "fallback"
    try {
        $null = Invoke-Adb @("shell", "uiautomator", "dump")
        $xml = (Invoke-Adb @("shell", "cat", "/sdcard/window_dump.xml")) -join "`n"
        $pat = 'resource-id="[^"]*' + [regex]::Escape($ResourceId) + '"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        $m = [regex]::Match($xml, $pat)
        if ($m.Success) {
            $x = [int](([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2)
            $y = [int](([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2)
            $how = "uiautomator"
        }
    } catch { Write-Warning "uiautomator lookup for $ResourceId failed: $_" }
    Write-Host "     Tap $ResourceId via $how ($x, $y)" -ForegroundColor DarkGray
    return @($x, $y)
}

function ConvertTo-AdbInputText {
    param([string]$Text)
    # adb shell input text requires spaces as %s and shell-special characters escaped
    $sb = New-Object System.Text.StringBuilder
    foreach ($char in $Text.ToCharArray()) {
        switch ($char) {
            '%'  { [void]$sb.Append('%%') }
            ' '  { [void]$sb.Append('%s') }
            '\'  { [void]$sb.Append('\\') }
            '&'  { [void]$sb.Append('\&') }
            '<'  { [void]$sb.Append('\<') }
            '>'  { [void]$sb.Append('\>') }
            '('  { [void]$sb.Append('\(') }
            ')'  { [void]$sb.Append('\)') }
            ';'  { [void]$sb.Append('\;') }
            '|'  { [void]$sb.Append('\|') }
            '$'  { [void]$sb.Append('\$') }
            '`'  { [void]$sb.Append('\`') }
            '"'  { [void]$sb.Append('\"') }
            "'"  { [void]$sb.Append("\'") }
            '?'  { [void]$sb.Append('\?') }
            '*'  { [void]$sb.Append('\*') }
            '~'  { [void]$sb.Append('\~') }
            '!'  { [void]$sb.Append('\!') }
            '['  { [void]$sb.Append('\[') }
            ']'  { [void]$sb.Append('\]') }
            '{'  { [void]$sb.Append('\{') }
            '}'  { [void]$sb.Append('\}') }
            default { [void]$sb.Append($char) }
        }
    }
    return $sb.ToString()
}

function ConvertTo-ShellSingleQuoted {
    param([string]$Text)
    $escaped = $Text.Replace("'", "'\''")
    return "'" + $escaped + "'"
}

# Reads the phone CPU features once through adb. Returns ReadOk = $false when
# /proc/cpuinfo or the Features line could not be read, so callers keep the safe
# default (push both models rather than risk omitting a needed file). Every core
# reports its own Features line, so each one is checked for the asimddp (Arm
# dot product) token.
function Get-CpuFeatureStatus {
    $cpuInfo = (@(Invoke-Adb @("shell", "cat", "/proc/cpuinfo")) -join "`n")
    $featureMatches = [regex]::Matches($cpuInfo, 'Features\s*:\s*([^\r\n]+)')
    $readOk = (-not [string]::IsNullOrWhiteSpace($cpuInfo)) -and ($featureMatches.Count -gt 0)
    $hasAsimddp = $false
    foreach ($featureMatch in $featureMatches) {
        if ($featureMatch.Groups[1].Value -match '(^|\s)asimddp(\s|$)') {
            $hasAsimddp = $true
            break
        }
    }
    return [PSCustomObject]@{ ReadOk = $readOk; HasAsimddp = $hasAsimddp }
}

$ScreenrecordProc = $null
$runStartTime = $null

try {
    # -------------------------------------------------------------------------
    # 1. Install Debug APK
    # -------------------------------------------------------------------------
    Write-Host "`n[1/8] Installing debug APK (--user 0 so work profiles and Secure Folder are never touched)..." -ForegroundColor Yellow
    if (Test-Path $ApkPath) {
        Invoke-Adb @("install", "--user", "0", "-r", "-d", $ApkPath)
    } else {
        Write-Warning "APK not found at $ApkPath. Proceeding with currently installed package if available."
    }

    # -------------------------------------------------------------------------
    # 2. First launch (DT-1): am start --user 0 -W, wait 3 s, force-stop --user 0,
    #    and only then create the models folder and push models.
    #    WHY: if adb creates /sdcard/Android/data/org.ps3.sentinel before the app's
    #    first launch, Android 14 on the moto g73 denies the app access to that
    #    folder and the app reports every model missing. The app's own first launch
    #    creates its folder; the force-stop ensures the folder is owned by the app
    #    before adb writes into it.
    # -------------------------------------------------------------------------
    Write-Host "`n[2/8] First launch (must precede any adb-created folder)..." -ForegroundColor Yellow
    Invoke-Adb @("shell", "am", "start", "--user", "0", "-W", "-n", $MainActivity)
    Start-Sleep -Seconds 3
    Invoke-Adb @("shell", "am", "force-stop", "--user", "0", $PackageName)

    # Only now that the app owns its external folder, create the models folder.
    Invoke-Adb @("shell", "mkdir", "-p", $DeviceModelDir)

    # -------------------------------------------------------------------------
    # 3. Push Models (phone names from sentinel/data/model_files.json)
    # -------------------------------------------------------------------------
    Write-Host "`n[3/8] Pushing models to $DeviceModelDir (model_files.json specifications)..." -ForegroundColor Yellow

    if ([System.IO.Path]::IsPathRooted($SmsFp32Path)) {
        $smsFp32Local = $SmsFp32Path
    } else {
        $smsFp32Local = Join-Path $RepoRoot $SmsFp32Path
    }

    $cpuStatus = Get-CpuFeatureStatus
    if (-not $cpuStatus.ReadOk) {
        $pushSmsInt8 = $true
        $pushSmsFp32 = $true
    } elseif ($cpuStatus.HasAsimddp) {
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

    # Single source for phone file names: sentinel/data/model_files.json (F2).
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
        $modelsToPush += @{ Role = $role; Local = $roleToLocal[$role]; RemoteName = $entry.phone }
    }
    $modelsToPush = $modelsToPush | Sort-Object -Property "Role"

    foreach ($m in $modelsToPush) {
        $srcPath = Join-Path $RepoRoot $m.Local
        $dstPath = "$DeviceModelDir/$($m.RemoteName)"
        if (Test-Path $srcPath) {
            Write-Host "  Pushing $($m.RemoteName)..." -ForegroundColor Green
            Invoke-Adb @("push", $srcPath, $dstPath)
        } else {
            Write-Warning "  Source model file not found: $srcPath"
        }
    }

    $smsInt8Remote = "$DeviceModelDir/sms_int8.pte"
    if (-not $pushSmsInt8) {
        Write-Host "  Skipping sms_int8.pte: phone does not have the Arm dot-product feature, so the app uses sms_fp32 only; removed any leftover from older pushes." -ForegroundColor DarkGray
        Invoke-Adb @("shell", "rm", "-f", $smsInt8Remote)
    }

    $smsFp32Entry = $modelFiles.files.sms_fp32
    $smsFp32PhoneName = if ($smsFp32Entry) { $smsFp32Entry.phone } else { "sms_fp32.pte" }
    $smsFp32Remote = "$DeviceModelDir/$smsFp32PhoneName"

    if (-not $pushSmsFp32) {
        if ($cpuStatus.HasAsimddp) {
            Write-Host "  Skipping ${smsFp32PhoneName}: phone has the Arm dot-product feature, so the app uses sms_int8 only; removed any leftover from older pushes." -ForegroundColor DarkGray
        } else {
            Write-Host "  Skipping ${smsFp32PhoneName}: file not present locally; removed any leftover from older pushes." -ForegroundColor DarkGray
        }
        Invoke-Adb @("shell", "rm", "-f", $smsFp32Remote)
    } elseif (Test-Path $smsFp32Local) {
        Write-Host "  Pushing $smsFp32PhoneName (optional, for phones without dot product)..." -ForegroundColor Green
        Invoke-Adb @("push", $smsFp32Local, $smsFp32Remote)
    } else {
        Write-Host "  SMS fp32 model not present locally ($smsFp32Local); skipping optional file." -ForegroundColor DarkGray
    }

    # Push the role files plus sms_fp32.pte when it was pushed.
    $pushedFiles = @()
    foreach ($m in $modelsToPush) {
        $srcPath = Join-Path $RepoRoot $m.Local
        if (Test-Path $srcPath) {
            $pushedFiles += @{ Local = $srcPath; Remote = "$DeviceModelDir/$($m.RemoteName)"; Name = $m.RemoteName }
        }
    }
    if ($pushSmsFp32 -and (Test-Path $smsFp32Local)) {
        $pushedFiles += @{ Local = $smsFp32Local; Remote = $smsFp32Remote; Name = $smsFp32PhoneName }
    }

    # Generate models.sha256 from the local files just pushed and push it (SEC-01).
    $manifestOut = Join-Path $OutDir "models.sha256"
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $py = $venvPy } else { $py = "python" }
    $manifestScript = Join-Path $RepoRoot "deploy/android/write_models_manifest.py"
    $roleArgs = @("--model-files", $modelFilesPath, "--out", $manifestOut)
    foreach ($m in $modelsToPush) {
        $roleArgs += @("--role", "$($m.Role)=$($m.Local)")
    }
    if ($pushSmsFp32 -and (Test-Path $smsFp32Local)) {
        $roleArgs += @("--role", "sms_fp32=$smsFp32Local")
    }
    Write-Host "  Generating $manifestOut from local model files..." -ForegroundColor Green
    & $py $manifestScript @roleArgs
    if ($LASTEXITCODE -ne 0) {
        throw "write_models_manifest.py failed when generating $manifestOut"
    }
    Write-Host "  Pushing models.sha256..." -ForegroundColor Green
    Invoke-Adb @("push", $manifestOut, "$DeviceModelDir/models.sha256")
    $pushedFiles += @{ Local = $manifestOut; Remote = "$DeviceModelDir/models.sha256"; Name = "models.sha256" }

    # Verify every pushed file with sha256sum on the phone against the local hash.
    Write-Host "  Verifying pushed files with sha256sum on the phone..." -ForegroundColor Yellow
    foreach ($f in $pushedFiles) {
        $localHash = (Get-FileHash -Path $f.Local -Algorithm SHA256).Hash.ToLower()
        $remoteLine = ((Invoke-Adb @("shell", "sha256sum", $f.Remote)) -join "`n").Trim()
        $remoteHash = ""
        if ($remoteLine) {
            $remoteHash = (($remoteLine -split '\s+')[0]).ToLower()
        }
        if ($remoteHash -ne $localHash) {
            throw "SHA-256 mismatch for $($f.Name): local $localHash != phone $remoteHash ($($f.Remote))"
        }
        Write-Host "    Verified $($f.Name) SHA-256 $($localHash.Substring(0, 12))..." -ForegroundColor Green
    }

    # Verify pushed files
    Invoke-Adb @("shell", "ls", "-lh", $DeviceModelDir)

    # Grant POST_NOTIFICATIONS only when the phone API level is 33 or higher (DT-10).
    # The permission was introduced in Android 13 (API 33); below that notifications
    # need no runtime grant and the grant would error.
    $sdkLevelText = ((Invoke-Adb @("shell", "getprop", "ro.build.version.sdk")) -join "").Trim()
    $sdkLevel = 0
    if (-not [int]::TryParse($sdkLevelText, [ref]$sdkLevel)) {
        Write-Warning "Could not read ro.build.version.sdk ('$sdkLevelText'); skipping POST_NOTIFICATIONS grant."
    } elseif ($sdkLevel -ge 33) {
        Write-Host "  Granting POST_NOTIFICATIONS (API $sdkLevel)..." -ForegroundColor Green
        Invoke-Adb @("shell", "pm", "grant", "--user", "0", $PackageName, "android.permission.POST_NOTIFICATIONS")
    } else {
        Write-Host "  Skipping POST_NOTIFICATIONS grant on API $sdkLevel (< 33); notifications need no runtime grant." -ForegroundColor DarkGray
    }

    # -------------------------------------------------------------------------
    # 4. Relaunch Application (logcat is never cleared; reads use logcat -T)
    # -------------------------------------------------------------------------
    Write-Host "`n[4/8] Relaunching app to register new models..." -ForegroundColor Yellow
    $runStartTime = Get-PhoneLogTime
    Invoke-Adb @("shell", "am", "force-stop", "--user", "0", $PackageName)
    Start-Sleep -Seconds 1
    Invoke-Adb @("shell", "am", "start", "--user", "0", "-W", "-n", $MainActivity)
    Start-Sleep -Seconds 4

    # -------------------------------------------------------------------------
    # 5. Enable Airplane Mode (NFR-06 Offline Proof)
    # -------------------------------------------------------------------------
    Write-Host "`n[5/8] Enabling Airplane Mode (offline verification)..." -ForegroundColor Yellow
    Invoke-Adb @("shell", "cmd", "connectivity", "airplane-mode", "enable")
    Start-Sleep -Seconds 2

    # -------------------------------------------------------------------------
    # 6. Load Demo Messages
    # -------------------------------------------------------------------------
    Write-Host "`n[6/8] Loading demo threat messages from bench/bench_messages.txt..." -ForegroundColor Yellow
    $demoFilePath = Join-Path $RepoRoot "bench/bench_messages.txt"
    if (-not (Test-Path $demoFilePath)) {
        throw "Demo messages file not found: $demoFilePath"
    }
    $demoMessages = Get-Content -Path $demoFilePath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 5
    Write-Host "  Loaded $($demoMessages.Count) messages." -ForegroundColor Green

    # -------------------------------------------------------------------------
    # 7. Exercise Demo Threat Messages
    # -------------------------------------------------------------------------
    Write-Host "`n[7/8] Interacting with UI: Typing and analysing demo threat messages..." -ForegroundColor Yellow

    # Record at the phone's actual display size (C-25); fall back to 1080x2408.
    $recordSize = "1080x2408"
    $wmSizeText = ((Invoke-Adb @("shell", "wm", "size")) -join "`n")
    $wmMatches = [regex]::Matches($wmSizeText, '(\d+)x(\d+)')
    if ($wmMatches.Count -gt 0) {
        $lastWm = $wmMatches[$wmMatches.Count - 1]
        $recordSize = "$($lastWm.Groups[1].Value)x$($lastWm.Groups[2].Value)"
    }

    $msgIndex = 1
    foreach ($msg in $demoMessages) {
        Write-Host "  -> Message $($msgIndex): $($msg.Substring(0, [Math]::Min(60, $msg.Length)))..." -ForegroundColor White

        # Logcat is never cleared (C-11); remember where this message's logs start.
        $msgStartTime = Get-PhoneLogTime

        # Record one file per message (msg_N.mp4) started before sending to avoid 180s screenrecord limit
        $devVideo = "/sdcard/msg_${msgIndex}.mp4"
        $recordArgs = @("-s", $Serial, "shell", "screenrecord", "--size", $recordSize, "--time-limit", "180", $devVideo)
        $msgScreenProc = Start-Process -FilePath $AdbPath -ArgumentList $recordArgs -PassThru
        Start-Sleep -Milliseconds 500

        # Send via share intent (C-25): `input text` mangles Unicode (demo Hinglish
        # line), while the SEND intent carries the full text, like device_test.ps1.
        $quoted = ConvertTo-ShellSingleQuoted -Text $msg
        $inner = "am start --user 0 -a android.intent.action.SEND -t text/plain " +
            "--es android.intent.extra.TEXT $quoted -n $MainActivity"
        Invoke-Adb @("shell", $inner) | Out-Null
        Start-Sleep -Milliseconds 500

        # Poll adb logcat -d -s PS3Llama every 2s until stats line appears (timeout 60s)
        # Unified rule: poll up to 60s. Stop early if after 10s no PS3Llama line has appeared and logcat for
        # tag PS3Sentinel or pipeline indicates low risk; otherwise poll full 60s (Pipeline.kt and MainActivity.kt
        # emit no low-risk log lines).
        Write-Host "     Polling logcat PS3Llama for inference completion (up to 60s)..." -ForegroundColor DarkGray
        $pollTimeout = 60
        $elapsed = 0
        $llamaDone = $false
        $lowRiskDone = $false

        while ($elapsed -lt $pollTimeout) {
            Start-Sleep -Seconds 2
            $elapsed += 2
            $llamaArgs = @("logcat", "-d")
            if ($msgStartTime) { $llamaArgs += @("-T", $msgStartTime) }
            $llamaArgs += @("-s", "PS3Llama")
            $llamaLogs = Invoke-Adb $llamaArgs
            if ($llamaLogs -match "PS3Llama" -and ($llamaLogs -match "\{" -or $llamaLogs -match "ttft|decode|advice|stats")) {
                $llamaDone = $true
                Write-Host "     Llama advice generated in ~${elapsed}s." -ForegroundColor Green
                break
            }

            if ($elapsed -ge 10) {
                $sentinelArgs = @("logcat", "-d")
                if ($msgStartTime) { $sentinelArgs += @("-T", $msgStartTime) }
                $sentinelArgs += @("-s", "PS3Sentinel:V", "PS3Sms:V")
                $sentinelLogs = Invoke-Adb $sentinelArgs
                if ($sentinelLogs -match "(?i)low[- ]?risk") {
                    $lowRiskDone = $true
                    Write-Host "     Low-risk message completed without Llama (detected in ~${elapsed}s)." -ForegroundColor Green
                    break
                }
            }
        }

        if ($llamaDone) {
            Start-Sleep -Seconds 1
        } elseif ($lowRiskDone) {
            Start-Sleep -Seconds 1
        } else {
            Write-Host "     Poll finished after ${pollTimeout}s (no Llama advice generated; low-risk message or timed out)." -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }

        # Save per-message logcat (only lines since this message started)
        $msgLogcatArgs = @("logcat", "-d")
        if ($msgStartTime) { $msgLogcatArgs += @("-T", $msgStartTime) }
        $msgLogcatArgs += @("-s", "PS3Llama:V", "PS3Sms:V", "PS3Sentinel:V")
        $msgLogcat = Invoke-Adb $msgLogcatArgs
        $msgLogcat | Out-File -FilePath "$OutDir/logcat_msg_${msgIndex}.txt" -Encoding utf8
        Write-Host "     Saved message logcat: $OutDir/logcat_msg_${msgIndex}.txt" -ForegroundColor DarkGray

        # Take on-device screenshot
        $deviceCap = "/sdcard/msg_${msgIndex}.png"
        Invoke-Adb @("shell", "screencap", "-p", $deviceCap)
        Write-Host "     Saved screenshot on device: $deviceCap" -ForegroundColor DarkGray

        # Stop screen recording for this message
        Invoke-Adb @("shell", "pkill", "-2", "screenrecord")
        Start-Sleep -Seconds 1
        if ($msgScreenProc -and -not $msgScreenProc.HasExited) {
            Stop-Process -Id $msgScreenProc.Id -Force -ErrorAction SilentlyContinue
        }

        $msgIndex++
    }

    # -------------------------------------------------------------------------
    # 8. Pull Artifacts
    # -------------------------------------------------------------------------
    Write-Host "`n[8/8] Pulling results and logs..." -ForegroundColor Yellow

    # Pull videos and screenshots
    for ($i = 1; $i -lt $msgIndex; $i++) {
        $devVid = "/sdcard/msg_${i}.mp4"
        $localVid = "$OutDir/msg_${i}.mp4"
        Write-Host "  Pulling $devVid -> $localVid..." -ForegroundColor Green
        Invoke-Adb @("pull", $devVid, $localVid)

        $devCap = "/sdcard/msg_${i}.png"
        $localCap = "$OutDir/msg_${i}.png"
        Write-Host "  Pulling $devCap -> $localCap..." -ForegroundColor Green
        Invoke-Adb @("pull", $devCap, $localCap)
    }

    # Capture logcat lines for PS3Llama and PS3Sms (only this run's lines)
    Write-Host "  Exporting logcat for PS3Llama and PS3Sms tags..." -ForegroundColor Green
    $exportArgs = @("logcat", "-d")
    if ($runStartTime) { $exportArgs += @("-T", $runStartTime) }
    $exportArgs += @("-s", "PS3Llama:V", "PS3Sms:V", "PS3Sentinel:V")
    $logcatLines = Invoke-Adb $exportArgs
    $logcatLines | Out-File -FilePath "$OutDir/logcat_ps3.txt" -Encoding utf8

    # Capture dumpsys meminfo (NFR-04 Peak RAM verification)
    Write-Host "  Exporting dumpsys meminfo $PackageName..." -ForegroundColor Green
    $meminfo = Invoke-Adb @("shell", "dumpsys", "meminfo", $PackageName)
    $meminfo | Out-File -FilePath "$OutDir/dumpsys_meminfo.txt" -Encoding utf8

    Write-Host "`nAndroid test run finished successfully! Results stored in: $OutDir" -ForegroundColor Green
}
finally {
    # Restore connectivity FIRST: stopping screenrecord must never prevent it.
    try {
        Write-Host "`n[CLEANUP] Disabling Airplane Mode..." -ForegroundColor Yellow
        Invoke-Adb @("shell", "cmd", "connectivity", "airplane-mode", "disable")
    } catch {
        Write-Warning "[CLEANUP] airplane-mode disable failed: $_"
    }
    try {
        $recordPids = Invoke-Adb @("shell", "pidof", "screenrecord")
        if ($recordPids) {
            $recordPid = ($recordPids -join " " -split "\s+")[0]
            Write-Host "[CLEANUP] Stopping screenrecord pid $recordPid..." -ForegroundColor Yellow
            Invoke-Adb @("shell", "kill", "-2", "$recordPid")
        } else {
            Write-Host "[CLEANUP] No screenrecord process running; skipping stop." -ForegroundColor DarkGray
        }
    } catch {
        Write-Warning "[CLEANUP] screenrecord stop failed: $_"
    }
    try {
        Start-Sleep -Seconds 1
        Write-Host "[CLEANUP] Removing phone files outside the app package (/sdcard/msg_*.mp4, /sdcard/msg_*.png, /sdcard/window_dump.xml)..." -ForegroundColor Yellow
        Invoke-Adb @("shell", "rm", "-f", "/sdcard/msg_*.mp4", "/sdcard/msg_*.png", "/sdcard/window_dump.xml")
    } catch {
        Write-Warning "[CLEANUP] removing /sdcard test files failed: $_"
    }
    try {
        $airplaneOn = ((Invoke-Adb @("shell", "settings", "get", "global", "airplane_mode_on") | Out-String).Trim())
        if ($airplaneOn -ne "0") {
            Write-Host "[CLEANUP] airplane_mode_on is '$airplaneOn'; retrying disable once..." -ForegroundColor Yellow
            Invoke-Adb @("shell", "cmd", "connectivity", "airplane-mode", "disable")
            $airplaneOn = ((Invoke-Adb @("shell", "settings", "get", "global", "airplane_mode_on") | Out-String).Trim())
        }
        if ($airplaneOn -ne "0") {
            Write-Host "========================================================================" -ForegroundColor Red
            Write-Host "WARNING: Airplane mode is still ON (airplane_mode_on='$airplaneOn')." -ForegroundColor Red
            Write-Host "Turn airplane mode OFF by hand!" -ForegroundColor Red
            Write-Host "========================================================================" -ForegroundColor Red
        } else {
            Write-Host "[CLEANUP] Device connectivity restored." -ForegroundColor Green
        }
    } catch {
        Write-Warning "[CLEANUP] airplane mode verification failed: $_"
    }
}
