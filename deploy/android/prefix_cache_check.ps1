<#
.SYNOPSIS
    Four-pass prefix-cache A/B check on a real phone via ADB.

.DESCRIPTION
    Reads the first Count non-empty lines of bench/llm_prompts.txt and runs
    them four times through the share entry point: off forward, on forward, then
    off and on again in REVERSED order. Modes off/on are with prefix_cache.off
    present or absent (off forward and on forward, with prefix_cache.on removed
    for off and present for on), and off_rev/on_rev are the reversed-order
    repeats. Each advice logs one PS3Bench line; the script collects runs.csv plus
    summary.txt under bench/results/f14_prefix_<timestamp>/ and always removes
    both flag files (prefix_cache is on by default now). GapSec is the pause
    after each answer before the next message.
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$Serial,

    [Parameter()]
    [string]$Adb = "",

    [Parameter()]
    [int]$Count = 20,

    [Parameter()]
    [int]$TimeoutSec = 90,

    [Parameter()]
    [int]$GapSec = 15
)

if (-not $Serial) {
    $Serial = $env:ANDROID_SERIAL
}

# Resolve ADB path: explicit -Adb wins, then LOCALAPPDATA SDK, then adb on PATH.
if (-not $Adb) {
    $sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    if (Test-Path $sdkAdb) {
        $Adb = $sdkAdb
    } else {
        $adbCmd = Get-Command adb -ErrorAction SilentlyContinue
        if ($adbCmd) {
            $Adb = $adbCmd.Source
        } else {
            $Adb = "adb.exe"
        }
    }
}
if (($Adb -ne "adb.exe") -and (-not (Test-Path $Adb))) {
    Write-Error "ADB not found at $Adb. Pass -Adb <path> to adb.exe."
    exit 1
}

# Single-device fallback when neither -Serial nor ANDROID_SERIAL was given.
if (-not $Serial) {
    $deviceLines = @()
    try {
        $deviceLines = & $Adb devices 2>$null
    } catch {
        $deviceLines = @()
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
    Write-Error 'ANDROID_SERIAL is not set and -Serial was not provided, and no single connected device was found. Set ANDROID_SERIAL (e.g. <adb-serial>), pass -Serial, or connect one device.'
    exit 1
}

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$PackageName = 'org.ps3.sentinel'
$MainActivity = 'org.ps3.sentinel/.ui.MainActivity'
$DeviceModelDir = "/sdcard/Android/data/$PackageName/files/models"
$FlagPath = "$DeviceModelDir/prefix_cache.on"
$OffFlagPath = "$DeviceModelDir/prefix_cache.off"
$WarmupTimeoutSec = 60
$WarmupPollSec = 2
$PollIntervalSec = 2
$PromptsFile = Join-Path $RepoRoot 'bench\llm_prompts.txt'

$DateStamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$OutDir = Join-Path $RepoRoot "bench/results/f14_prefix_$DateStamp"
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

function Invoke-Adb {
    param([string[]]$Arguments)
    # $ErrorActionPreference is Stop at script level, which would turn any
    # adb warning on stderr into a terminating error and abort the run
    # (C-12). Tolerate adb warnings: run with Continue and stderr dropped,
    # like Invoke-Adb in full_test.ps1/device_test.ps1.
    $allArgs = @('-s', $Serial) + $Arguments
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Adb $allArgs 2>$null
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

# Phone-local "MM-DD HH:MM:SS.mmm" for logcat -T, or $null when unavailable.
# Logcat is never cleared (C-11, R2C-7): clearing wipes every app's logs.
function Get-PhoneLogTime {
    $raw = (Invoke-Adb @('shell', "date '+%m-%d %H:%M:%S.000'") -join "`n")
    $found = [regex]::Matches($raw, '\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}')
    if ($found.Count -gt 0) { return $found[$found.Count - 1].Value }
    return $null
}

function Get-BenchLines {
    param([string]$Since = $null)
    $logArgs = @('logcat', '-d')
    if ($Since) { $logArgs += @('-T', $Since) }
    $logArgs += @('-s', 'PS3Bench')
    $raw = Invoke-Adb $logArgs
    if ($null -eq $raw) { return @() }
    return @($raw | Where-Object { $_ -match 'prompt_path=' })
}

function Parse-BenchLine {
    param([string]$Line)
    $mPath = [regex]::Match($Line, 'prompt_path=([a-z_]+)')
    $mTok = [regex]::Match($Line, 'prompt_tokens=(\d+)')
    $mTtft = [regex]::Match($Line, 'ttft_ms=([0-9]+(\.[0-9]+)?)')
    $mDec = [regex]::Match($Line, 'decode_tok_s=([0-9]+(\.[0-9]+)?)')
    $mHash = [regex]::Match($Line, 'advice_sha8=([0-9a-f]{8})')
    $promptPath = if ($mPath.Success) { $mPath.Groups[1].Value } else { '' }
    $promptTokens = if ($mTok.Success) { [int]$mTok.Groups[1].Value } else { 0 }
    $ttft = if ($mTtft.Success) { [double]$mTtft.Groups[1].Value } else { 0.0 }
    $decode = if ($mDec.Success) { [double]$mDec.Groups[1].Value } else { 0.0 }
    $hash = if ($mHash.Success) { $mHash.Groups[1].Value } else { '' }
    return [PSCustomObject]@{
        promptPath = $promptPath
        promptTokens = $promptTokens
        ttftMs = $ttft
        decodeTokS = $decode
        adviceSha8 = $hash
    }
}

function ConvertTo-ShellSingleQuoted {
    param([string]$Text)
    $escaped = $Text.Replace("'", "'\''")
    return "'" + $escaped + "'"
}

function Get-Percentile {
    param([double[]]$Sorted, [double]$P)
    if ($null -eq $Sorted -or $Sorted.Count -eq 0) { return 0.0 }
    $idx = [int][Math]::Ceiling($P / 100.0 * $Sorted.Count) - 1
    if ($idx -lt 0) { $idx = 0 }
    if ($idx -ge $Sorted.Count) { $idx = $Sorted.Count - 1 }
    return $Sorted[$idx]
}

function Wait-ForWarmup {
    param([string]$Since = $null)
    $elapsed = 0
    while ($elapsed -lt $WarmupTimeoutSec) {
        Start-Sleep -Seconds $WarmupPollSec
        $elapsed += $WarmupPollSec
        $logArgs = @('logcat', '-d')
        if ($Since) { $logArgs += @('-T', $Since) }
        $logArgs += @('-s', 'PS3Sms:V', 'PS3Bench:V')
        $logs = Invoke-Adb $logArgs
        $text = ($logs -join "`n")
        if ($text -match 'prefix cache') {
            return $true
        }
    }
    return $false
}

Write-Host '============================================================'
Write-Host '  PS3 prefix cache check (off/on forward + reversed)'
Write-Host "  Serial: $Serial"
Write-Host "  ADB: $Adb"
Write-Host "  Prompts: $PromptsFile (Count=$Count, TimeoutSec=$TimeoutSec, GapSec=$GapSec)"
Write-Host "  Out: $OutDir"
Write-Host '============================================================'

if (-not (Test-Path $PromptsFile)) {
    Write-Error "Prompts file not found: $PromptsFile"
    exit 1
}

$allMessages = @(Get-Content -Path $PromptsFile | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$messages = @($allMessages | Select-Object -First $Count)
if ($messages.Count -eq 0) {
    Write-Error 'No non-empty prompts found.'
    exit 1
}
Write-Host "Loaded $($messages.Count) messages"

$rows = @()

try {
    Invoke-Adb @('shell', 'mkdir', '-p', $DeviceModelDir)
    $passes = @(
        @{ Label = 'off'; FlagOn = $false; Reversed = $false },
        @{ Label = 'on'; FlagOn = $true; Reversed = $false },
        @{ Label = 'off_rev'; FlagOn = $false; Reversed = $true },
        @{ Label = 'on_rev'; FlagOn = $true; Reversed = $true }
    )
    foreach ($pass in $passes) {
        $mode = $pass.Label
        Write-Host "`n--- Mode $mode (Reversed=$($pass.Reversed)) ---"
        if (-not $pass.FlagOn) {
            Invoke-Adb @('shell', 'touch', $OffFlagPath)
            Invoke-Adb @('shell', 'rm', '-f', $FlagPath)
        }
        else {
            Invoke-Adb @('shell', 'rm', '-f', $OffFlagPath)
            Invoke-Adb @('shell', 'touch', $FlagPath)
        }
        # Never clear logcat (R2C-7): only read lines after this pass's start.
        $passStartTime = Get-PhoneLogTime
        Invoke-Adb @('shell', 'am', 'force-stop', '--user', '0', $PackageName)
        Start-Sleep -Seconds 1
        Invoke-Adb @('shell', 'am', 'start', '--user', '0', '-W', '-n', $MainActivity)
        $warmed = Wait-ForWarmup -Since $passStartTime
        if ($warmed) {
            Write-Host '  Warm-up marker seen (prefix cache log line).'
        }
        else {
            Write-Host "  Warm-up marker not seen within ${WarmupTimeoutSec}s; continuing."
        }

        $orderedIndices = @()
        for ($k = 0; $k -lt $messages.Count; $k++) { $orderedIndices += $k }
        if ($pass.Reversed) { [array]::Reverse($orderedIndices) }

        for ($pos = 0; $pos -lt $orderedIndices.Count; $pos++) {
            $i = $orderedIndices[$pos]
            $msg = $messages[$i]
            $idx = $i + 1
            $beforeCount = @(Get-BenchLines -Since $passStartTime).Count
            $quoted = ConvertTo-ShellSingleQuoted -Text $msg
            $inner = "am start --user 0 -a android.intent.action.SEND -t text/plain " +
                "--es android.intent.extra.TEXT $quoted -n $MainActivity"
            Invoke-Adb @('shell', $inner)

            $found = $null
            $elapsed = 0
            while ($elapsed -le $TimeoutSec) {
                Start-Sleep -Seconds $PollIntervalSec
                $elapsed += $PollIntervalSec
                $lines = @(Get-BenchLines -Since $passStartTime)
                if ($lines.Count -gt $beforeCount) {
                    $found = $lines[$lines.Count - 1]
                    break
                }
            }

            if ($null -eq $found) {
                Write-Host "  [$mode $idx/$($messages.Count)] TIMEOUT after ${TimeoutSec}s"
                $rows += [PSCustomObject]@{
                    mode = $mode
                    index = $idx
                    prompt_path = ''
                    prompt_tokens = 0
                    ttft_ms = 0.0
                    decode_tok_s = 0.0
                    advice_sha8 = ''
                }
            }
            else {
                $p = Parse-BenchLine -Line $found
                $rows += [PSCustomObject]@{
                    mode = $mode
                    index = $idx
                    prompt_path = $p.promptPath
                    prompt_tokens = $p.promptTokens
                    ttft_ms = $p.ttftMs
                    decode_tok_s = $p.decodeTokS
                    advice_sha8 = $p.adviceSha8
                }
                Write-Host "  [$mode $idx/$($messages.Count)] $($p.promptPath) ttft=$($p.ttftMs)ms hash=$($p.adviceSha8)"
            }
            if ($GapSec -gt 0 -and $pos -lt ($orderedIndices.Count - 1)) {
                Start-Sleep -Seconds $GapSec
            }
        }
    }
}
finally {
    try {
        Invoke-Adb @('shell', 'rm', '-f', $FlagPath, $OffFlagPath)
        Write-Host '[CLEANUP] Removed prefix_cache.on and prefix_cache.off from device.'
    }
    catch {
        Write-Warning 'Could not remove flag file from device.'
    }
}

$csvPath = Join-Path $OutDir 'runs.csv'
$rows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8

function Get-ValidRows {
    param([string]$Mode)
    return @($rows | Where-Object { $_.mode -eq $Mode -and $_.prompt_path -ne '' })
}

$offValid = @(Get-ValidRows -Mode 'off')
$onValid = @(Get-ValidRows -Mode 'on')
$offRevValid = @(Get-ValidRows -Mode 'off_rev')
$onRevValid = @(Get-ValidRows -Mode 'on_rev')

$offTtft = @($offValid | ForEach-Object { [double]$_.ttft_ms } | Sort-Object)
$onTtft = @($onValid | ForEach-Object { [double]$_.ttft_ms } | Sort-Object)
$offP50 = Get-Percentile -Sorted $offTtft -P 50
$offP95 = Get-Percentile -Sorted $offTtft -P 95
$onP50 = Get-Percentile -Sorted $onTtft -P 50
$onP95 = Get-Percentile -Sorted $onTtft -P 95

$offTokens = @($offValid | ForEach-Object { [double]$_.prompt_tokens })
$onTokens = @($onValid | ForEach-Object { [double]$_.prompt_tokens })
$offMeanTok = if ($offTokens.Count -gt 0) { ($offTokens | Measure-Object -Average).Average } else { 0.0 }
$onMeanTok = if ($onTokens.Count -gt 0) { ($onTokens | Measure-Object -Average).Average } else { 0.0 }

$offByIdx = @{}
foreach ($r in $offValid) { $offByIdx[$r.index] = $r }
$onByIdx = @{}
foreach ($r in $onValid) { $onByIdx[$r.index] = $r }
$offRevByIdx = @{}
foreach ($r in $offRevValid) { $offRevByIdx[$r.index] = $r }
$onRevByIdx = @{}
foreach ($r in $onRevValid) { $onRevByIdx[$r.index] = $r }

$identicalCount = 0
$tailOk = $true
$compared = 0
for ($i = 1; $i -le $messages.Count; $i++) {
    if ($offByIdx.ContainsKey($i) -and $onByIdx.ContainsKey($i)) {
        $compared++
        if ($offByIdx[$i].advice_sha8 -eq $onByIdx[$i].advice_sha8 -and $offByIdx[$i].advice_sha8 -ne '') {
            $identicalCount++
        }
        if (-not ([int]$onByIdx[$i].prompt_tokens -lt [int]$offByIdx[$i].prompt_tokens)) {
            $tailOk = $false
        }
    }
    else {
        $tailOk = $false
    }
}

$identicalOffOrder = 0
$offOrderOk = $true
for ($i = 1; $i -le $messages.Count; $i++) {
    if ($offByIdx.ContainsKey($i) -and $offRevByIdx.ContainsKey($i)) {
        if ($offByIdx[$i].advice_sha8 -eq $offRevByIdx[$i].advice_sha8 -and $offByIdx[$i].advice_sha8 -ne '') {
            $identicalOffOrder++
        } else {
            $offOrderOk = $false
        }
    } else {
        $offOrderOk = $false
    }
}

$identicalOnOrder = 0
$onOrderOk = $true
for ($i = 1; $i -le $messages.Count; $i++) {
    if ($onByIdx.ContainsKey($i) -and $onRevByIdx.ContainsKey($i)) {
        if ($onByIdx[$i].advice_sha8 -eq $onRevByIdx[$i].advice_sha8 -and $onByIdx[$i].advice_sha8 -ne '') {
            $identicalOnOrder++
        } else {
            $onOrderOk = $false
        }
    } else {
        $onOrderOk = $false
    }
}

$check1Pass = ($identicalCount -eq $messages.Count) -and ($offValid.Count -eq $messages.Count) -and ($onValid.Count -eq $messages.Count)
$check2Pass = $tailOk -and ($compared -eq $messages.Count)
$check3Pass = ($offValid.Count -gt 0) -and ($onValid.Count -gt 0) -and ($onP50 -lt $offP50)
$check4Pass = $offOrderOk -and ($identicalOffOrder -eq $messages.Count) -and ($offValid.Count -eq $messages.Count) -and ($offRevValid.Count -eq $messages.Count)
$check5Pass = $onOrderOk -and ($identicalOnOrder -eq $messages.Count) -and ($onValid.Count -eq $messages.Count) -and ($onRevValid.Count -eq $messages.Count)

function PassWord {
    param([bool]$Ok)
    if ($Ok) { return 'PASS' }
    return 'FAIL'
}

$noOutputRows = @($rows | Where-Object { [int]$_.prompt_tokens -eq 0 })

$summaryPath = Join-Path $OutDir 'summary.txt'
$lines = @(
    'PS3 prefix cache check summary',
    "date: $DateStamp",
    "serial: $Serial",
    "messages: $($messages.Count)",
    "off count: $($offValid.Count)",
    "on count: $($onValid.Count)",
    "off_rev count: $($offRevValid.Count)",
    "on_rev count: $($onRevValid.Count)",
    "off TTFT p50 ms: $offP50",
    "off TTFT p95 ms: $offP95",
    "on TTFT p50 ms: $onP50",
    "on TTFT p95 ms: $onP95",
    "off mean prompt_tokens: $offMeanTok",
    "on mean prompt_tokens: $onMeanTok",
    "identical advice_sha8: $identicalCount / $($messages.Count)",
    "identical off forward vs reversed: $identicalOffOrder / $($messages.Count)",
    "identical on forward vs reversed: $identicalOnOrder / $($messages.Count)",
    "check1 advice identical on all messages: $(PassWord $check1Pass)",
    "check2 on prompt_tokens < off on every message: $(PassWord $check2Pass)",
    "check3 TTFT p50 lower with on: $(PassWord $check3Pass)",
    "check4 off advice identical forward vs reversed: $(PassWord $check4Pass)",
    "check5 on advice identical forward vs reversed: $(PassWord $check5Pass)",
    'note: check1 can fail without a bug because prefilling the prompt in two chunks changes floating-point rounding, while checks 4 and 5 prove that no message affects another.'
)
foreach ($z in $noOutputRows) {
    $lines += "LLM_NO_OUTPUT mode=$($z.mode) index=$($z.index) prompt_tokens=$($z.prompt_tokens)"
}
$hasNoOutput = ($noOutputRows.Count -gt 0)
if ($check1Pass -and $check2Pass -and $check3Pass -and $check4Pass -and $check5Pass -and (-not $hasNoOutput)) {
    $lines += 'overall: PASS'
}
else {
    $lines += 'overall: FAIL'
}
$lines | Out-File -FilePath $summaryPath -Encoding utf8

Write-Host "`nWrote $csvPath"
Write-Host "Wrote $summaryPath"
Write-Host ($lines -join "`n")
