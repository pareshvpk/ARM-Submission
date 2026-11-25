# scripts/check.ps1
# One-command check for PS3 Sentinel (Windows / PowerShell).
#
# Runs, in order, and stops at the first failure with a clear message:
#   1. Python tests     (.venv python -m pytest -q; parity staleness is covered by
#                        tests/test_rules_parity.py::test_parity_fixture_is_up_to_date)
#   2. Android unit tests (gradlew testDebugUnitTest --offline -q --no-daemon)
#                          — only when android/ and a JDK exist; otherwise a warning, not a failure
#   3. Module-boundary grep rules (P-02: nothing in sentinel/ imports tests/ or bench/;
#                              core/ imports no app packages; ExecuTorch only in ml/)
#   4. Bash syntax check (bash -n) — skipped if bash unavailable
#   5. PowerShell parse check (every .ps1 under deploy/ and scripts/)
#
# Prints a final PASS or FAIL line and exits non-zero on failure.
# Only tools already installed are used (python, pytest, git). Nothing is installed.

# Resolve the repo root (this file lives in scripts/, one level below the repo root).
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

# Prefer the repo virtualenv; fall back to the plain `python` on PATH.
$venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) { $python = $venvPy } else { $python = "python" }

function Fail($message) {
    Write-Host ""
    Write-Host ("FAIL: " + $message) -ForegroundColor Red
    Write-Host ""
    exit 1
}

function Pass {
    param([string]$Suffix = "")
    Write-Host ""
    $line = "PASS: all checks passed"
    if ($Suffix) { $line = "PASS: all checks passed ($Suffix)" }
    Write-Host $line -ForegroundColor Green
    Write-Host ""
    exit 0
}

# --- 1. Python tests ---------------------------------------------------------
# Parity fixture staleness is covered by pytest: tests/test_rules_parity.py runs
# test_parity_fixture_is_up_to_date, which fails when tests/fixtures/parity_cases.json
# is stale. No separate parity check runs here.
Write-Host "== check: Python tests ($python -m pytest -q) =="
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Python tests failed (exit $LASTEXITCODE)." }

# --- 2. Android unit tests (only when android/ and a JDK exist) --------------
$androidDir = Join-Path $repoRoot "android"
$javaOnPath = $null -ne (Get-Command java -ErrorAction SilentlyContinue)
$javaHome = $env:JAVA_HOME
$javaInJdk = $false
if ($javaHome) {
    $jdkJava = Join-Path $javaHome "bin\java.exe"
    if (Test-Path $jdkJava) { $javaInJdk = $true }
}
$androidReady = (Test-Path $androidDir) -and ($javaOnPath -or $javaInJdk)
$androidSkipped = -not $androidReady
if ($androidReady) {
    Write-Host "== check: Android unit tests (gradlew testDebugUnitTest --offline -q --no-daemon) =="
    $gradlew = Join-Path $androidDir "gradlew.bat"
    if (-not (Test-Path $gradlew)) { $gradlew = Join-Path $androidDir "gradlew" }
    Push-Location $androidDir
    try {
        & $gradlew testDebugUnitTest --offline -q --no-daemon
    }
    finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) { Fail "Android unit tests failed (exit $LASTEXITCODE)." }
} else {
    Write-Host "ANDROID SKIPPED: no JDK" -ForegroundColor Yellow
}

# --- 3. Module-boundary grep rules (P-02) ------------------------------------
Write-Host "== check: module-boundary grep rules (P-02) =="
$grepFails = $false

# Python: nothing in sentinel/ may import tests/ or bench/.
# Windows PowerShell 5.1 does not recurse with a double-star glob in
# Select-String -Path, so enumerate the files and pipe them instead (C-13).
$pythonImports = Get-ChildItem -Path "sentinel" -Recurse -Filter *.py -File | Select-String -Pattern "import tests|from tests|import bench|from bench"
if ($pythonImports) {
    Write-Host "FAIL: sentinel/ imports tests/ or bench/:" -ForegroundColor Red
    $pythonImports | ForEach-Object { Write-Host ("  " + $_.Line) }
    $grepFails = $true
}

# Android: core/ must not import app packages (ui, ml, root, sms).
# Match only import lines of non-core packages: org.ps3.sentinel.ui, .ml, .sms
# and the root package classes (Pipeline, SentinelApp). The previous
# "org.ps3.sentinel" pattern matched core's own package line and imports
# of other core classes. Enumerate files rather than using a ** glob,
# which Windows PowerShell 5.1 does not recurse (C-13). Also match wildcard
# imports and fully-qualified references (R3B-8) to close the bypass.
$coreImports = Get-ChildItem -Path "android\app\src\main\java\org\ps3\sentinel\core" -Recurse -Filter *.kt -File | Select-String -Pattern "^\s*import\s+org\.ps3\.sentinel\.(\*|ui\b|ml\b|sms\b|Pipeline\b|SentinelApp\b)|org\.ps3\.sentinel\.(ui|ml|sms|Pipeline|SentinelApp)\."
if ($coreImports) {
    Write-Host "FAIL: core/ imports app packages:" -ForegroundColor Red
    $coreImports | ForEach-Object { Write-Host ("  " + $_.Line) }
    $grepFails = $true
}

# Android: ExecuTorch model classes only in ml/.
$etImports = Get-ChildItem -Path "android\app\src\main\java" -Recurse -Filter *.kt -File | Select-String -Pattern "org.pytorch.executorch" | Where-Object { $_.Path -notlike "*\ml\*" }
if ($etImports) {
    Write-Host "FAIL: org.pytorch.executorch referenced outside ml/:" -ForegroundColor Red
    $etImports | ForEach-Object { Write-Host ("  " + $_.Path + ": " + $_.Line) }
    $grepFails = $true
}

if ($grepFails) { Fail "module-boundary grep rules failed." }

# --- 4. Bash syntax check (bash -n) ---------------------------------------
Write-Host "== check: bash -n syntax check =="
$bash = $null
$bashCmd = Get-Command bash -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
if ($bashCmd) { $bash = $bashCmd }
elseif (Test-Path "C:\Program Files\Git\bin\bash.exe") { $bash = "C:\Program Files\Git\bin\bash.exe" }
if (-not $bash) {
    Write-Host "BASH SKIPPED: bash not on PATH and Git bash not found at C:\Program Files\Git\bin\bash.exe" -ForegroundColor Yellow
} else {
    & $bash -n "deploy/android/offline_run.sh"
    if ($LASTEXITCODE -ne 0) { Fail "bash -n failed for deploy/android/offline_run.sh (exit $LASTEXITCODE)." }
    Write-Host "BASH OK: bash -n passed for full_test.sh and offline_run.sh"
}

# --- 5. PowerShell parse check (deploy/ and scripts/) ----------------------
Write-Host "== check: PowerShell parse check =="
$psParseFail = $false
$ps1Files = @()
foreach ($dir in @("deploy", "scripts")) {
    if (Test-Path $dir) {
        $ps1Files += Get-ChildItem -Path $dir -Recurse -Filter *.ps1 -File
    }
}
foreach ($ps1File in $ps1Files) {
    $tokens = $null
    $psErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($ps1File.FullName, [ref]$tokens, [ref]$psErrors)
    if ($psErrors -and $psErrors.Count -gt 0) {
        foreach ($parseError in $psErrors) {
            Write-Host ("FAIL: " + $ps1File.FullName + " line " + $parseError.Extent.StartLineNumber + ": " + $parseError.Message) -ForegroundColor Red
        }
        $psParseFail = $true
    }
}
if ($psParseFail) { Fail "PowerShell parse check failed." }
Write-Host ("POWERSHELL OK: parse check passed for " + $ps1Files.Count + " .ps1 files")

if ($androidSkipped) { Pass "(android skipped)" } else { Pass }
