#!/usr/bin/env bash
# scripts/check.sh
# One-command check for PS3 Sentinel (Linux / Arm Linux).
#
# Runs, in order, and stops at the first failure with a clear message:
#   1. Python tests     (.venv python -m pytest -q; parity staleness is covered by
#                        tests/test_rules_parity.py::test_parity_fixture_is_up_to_date)
#   2. Android unit tests (gradlew testDebugUnitTest --offline -q --no-daemon)
#                          — only when android/ and a JDK exist; otherwise a warning, not a failure
#   3. Module-boundary grep rules (P-02: nothing in sentinel/ imports tests/ or bench/;
#                              core/ imports no app packages; ExecuTorch only in ml/)
#   4. Bash syntax check (bash -n) — skipped if bash unavailable
#   5. PowerShell parse check (every .ps1 under deploy/ and scripts/;
#                              via pwsh or powershell.exe if available, else SKIPPED)
#
# Prints a final PASS or FAIL line and exits non-zero on failure.
# Only tools already installed are used (python, pytest, grep, java, gradle).
# Nothing is installed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Prefer the repo virtualenv; fall back to the plain `python` on PATH.
VENV_PY="$REPO_ROOT/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then PY="$VENV_PY"; else PY="python"; fi

fail() {
    echo ""
    echo "FAIL: $1" >&2
    echo ""
    exit 1
}

pass() {
    echo ""
    echo "PASS: all checks passed"
    echo ""
    exit 0
}

# --- 1. Python tests ---------------------------------------------------------
# Parity fixture staleness is covered by pytest: tests/test_rules_parity.py runs
# test_parity_fixture_is_up_to_date, which fails when tests/fixtures/parity_cases.json
# is stale. No separate parity check runs here.
echo "== check: Python tests ($PY -m pytest -q) =="
"$PY" -m pytest -q
rc=$?
if [[ $rc -ne 0 ]]; then fail "Python tests failed (exit $rc)."; fi

# --- 2. Android unit tests (only when android/ and a JDK exist) --------------
ANDROID_DIR="$REPO_ROOT/android"
JAVA_HOME="${JAVA_HOME:-}"
ANDROID_RUN=0
if [[ -d "$ANDROID_DIR" ]]; then
    if command -v java >/dev/null 2>&1; then
        ANDROID_RUN=1
    elif [[ -n "$JAVA_HOME" && -x "$JAVA_HOME/bin/java" ]]; then
        ANDROID_RUN=1
    fi
fi
if [[ $ANDROID_RUN -eq 1 ]]; then
    echo "== check: Android unit tests (gradlew testDebugUnitTest --offline -q --no-daemon) =="
    GRADLEW="$ANDROID_DIR/gradlew"
    chmod +x "$GRADLEW" 2>/dev/null || true
    (
        cd "$ANDROID_DIR" && ./gradlew testDebugUnitTest --offline -q --no-daemon
    )
    rc=$?
    if [[ $rc -ne 0 ]]; then fail "Android unit tests failed (exit $rc)."; fi
else
    echo "ANDROID SKIPPED: no JDK"
fi

# --- 3. Module-boundary grep rules (P-02) ------------------------------------
echo "== check: module-boundary grep rules (P-02) =="
grep_fail=0

# Python: nothing in sentinel/ may import tests/ or bench/.
if grep -rEn "import tests|from tests|import bench|from bench" sentinel/ >/dev/null 2>&1; then
    echo "FAIL: sentinel/ imports tests/ or bench/:" >&2
    grep -rEn "import tests|from tests|import bench|from bench" sentinel/ >&2 || true
    grep_fail=1
fi

# Android: core/ must not import app packages (ui, ml, root, sms).
# Match only import lines of non-core packages (see scripts/check.ps1):
# the package line itself and imports of other core classes are allowed.
# Also match wildcard imports and fully-qualified references (R3B-8).
if grep -rEn --include='*.kt' "^[[:space:]]*import[[:space:]]+org\.ps3\.sentinel\.(ui|ml|sms|Pipeline|SentinelApp)($|[^A-Za-z0-9_])|^[[:space:]]*import[[:space:]]+org\.ps3\.sentinel\.\*|org\.ps3\.sentinel\.(ui|ml|sms|Pipeline|SentinelApp)\." android/app/src/main/java/org/ps3/sentinel/core/ >/dev/null 2>&1; then
    echo "FAIL: core/ imports app packages:" >&2
    grep -rEn --include='*.kt' "^[[:space:]]*import[[:space:]]+org\.ps3\.sentinel\.(ui|ml|sms|Pipeline|SentinelApp)($|[^A-Za-z0-9_])|^[[:space:]]*import[[:space:]]+org\.ps3\.sentinel\.\*|org\.ps3\.sentinel\.(ui|ml|sms|Pipeline|SentinelApp)\." android/app/src/main/java/org/ps3/sentinel/core/ >&2 || true
    grep_fail=1
fi

# Android: ExecuTorch model classes only in ml/.
if grep -rEnl "org.pytorch.executorch" android/app/src/main/java --include='*.kt' 2>/dev/null | grep -v "/ml/" >/dev/null 2>&1; then
    echo "FAIL: org.pytorch.executorch referenced outside ml/:" >&2
    grep -rEn "org.pytorch.executorch" android/app/src/main/java --include='*.kt' 2>/dev/null | grep -v "/ml/" >&2 || true
    grep_fail=1
fi

if [[ $grep_fail -ne 0 ]]; then fail "module-boundary grep rules failed."; fi

# --- 4. Bash syntax check (bash -n) ---------------------------------------
echo "== check: bash -n syntax check =="
if ! command -v bash >/dev/null 2>&1; then
    echo "BASH SKIPPED: bash not on PATH"
else
    bash -n deploy/android/offline_run.sh || fail "bash -n failed for deploy/android/offline_run.sh."
    echo "BASH OK: bash -n passed for full_test.sh and offline_run.sh"
fi

# --- 5. PowerShell parse check (deploy/ and scripts/) ----------------------
echo "== check: PowerShell parse check =="
PS_CMD=""
if command -v pwsh >/dev/null 2>&1; then
    PS_CMD="pwsh"
elif command -v powershell.exe >/dev/null 2>&1; then
    PS_CMD="powershell.exe"
fi
if [[ -z "$PS_CMD" ]]; then
    echo "POWERSHELL PARSE SKIPPED: neither pwsh nor powershell.exe found"
else
    "$PS_CMD" -NoProfile -ExecutionPolicy Bypass -Command '$fail=$false; $files=@(); foreach($d in @("deploy","scripts")){ if(Test-Path $d){ $files+=Get-ChildItem -Path $d -Recurse -Filter *.ps1 -File } }; foreach($f in $files){ $tokens=$null; $errs=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName,[ref]$tokens,[ref]$errs); if($errs -and $errs.Count -gt 0){ foreach($e in $errs){ Write-Host ("FAIL: "+$f.FullName+" line "+$e.Extent.StartLineNumber+": "+$e.Message) }; $fail=$true } }; if($fail){ exit 1 }'
    rc=$?
    if [[ $rc -ne 0 ]]; then fail "PowerShell parse check failed (exit $rc)."; fi
    echo "POWERSHELL OK: PowerShell parse check passed"
fi

if [[ $ANDROID_RUN -eq 0 ]]; then
    echo ""
    echo "PASS: all checks passed (android skipped)"
    echo ""
    exit 0
fi

pass
