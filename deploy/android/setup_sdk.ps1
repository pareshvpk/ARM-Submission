# Install the Android SDK command-line tools + platform 35 + build-tools on Windows (no Android Studio wizard).
# Uses Android Studio's bundled JDK (jbr). Run: powershell -ExecutionPolicy Bypass -File deploy\android\setup_sdk.ps1
$ErrorActionPreference = 'Stop'
# Expected values for commandlinetools-win-9862592_latest.zip: the SHA-1 and size come from Google repository2-3.xml (https://dl.google.com/android/repository/repository2-3.xml) and the SHA-256 was recorded on 2026-11-07 from a download that matched them.
$expectedSize = 138709020
$expectedSha1 = '5a03c5ce16f4c99ffe7bded82798b01b07a79bc0'
$expectedSha256 = '8597200d2622a0c720d0cf9a2b62b33d20eabdf56ce4cbd5ed5830c723a5fce5'
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
$defaultJbr = 'C:\Program Files\Android\Android Studio\jbr'
$shouldSetJavaHome = $false
if (-not $env:JAVA_HOME -or -not (Test-Path $env:JAVA_HOME)) {
    if (Test-Path $defaultJbr) {
        $env:JAVA_HOME = $defaultJbr
        $shouldSetJavaHome = $true
    }
}
New-Item -ItemType Directory -Force "$sdk\cmdline-tools" | Out-Null
if (-not (Test-Path "$sdk\cmdline-tools\latest\bin\sdkmanager.bat")) {
    $zip = "$env:TEMP\cmdline-tools.zip"
    Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-9862592_latest.zip' -OutFile $zip
    $actualSize = (Get-Item $zip).Length
    if ($actualSize -ne $expectedSize) {
        Remove-Item $zip -Force
        throw "cmdline-tools zip size mismatch: expected $expectedSize, actual $actualSize"
    }
    $actualSha1 = (Get-FileHash $zip -Algorithm SHA1).Hash
    if ($actualSha1 -ine $expectedSha1) {
        Remove-Item $zip -Force
        throw "cmdline-tools zip SHA1 mismatch: expected $expectedSha1, actual $actualSha1"
    }
    $actualSha256 = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($actualSha256 -ine $expectedSha256) {
        Remove-Item $zip -Force
        throw "cmdline-tools zip SHA256 mismatch: expected $expectedSha256, actual $actualSha256"
    }
    Expand-Archive $zip -DestinationPath "$sdk\cmdline-tools\tmp" -Force
    Move-Item "$sdk\cmdline-tools\tmp\cmdline-tools" "$sdk\cmdline-tools\latest"
    Remove-Item "$sdk\cmdline-tools\tmp" -Recurse -Force
}
$sm = "$sdk\cmdline-tools\latest\bin\sdkmanager.bat"
# Accept licences non-interactively, then install what the app build needs.
(1..20 | ForEach-Object { 'y' }) | & $sm --licenses | Out-Null  # one 'y' per licence prompt
& $sm 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'
[Environment]::SetEnvironmentVariable('ANDROID_HOME', $sdk, 'User')
if ($shouldSetJavaHome) {
    [Environment]::SetEnvironmentVariable('JAVA_HOME', $env:JAVA_HOME, 'User')
}
Write-Host "SDK_DONE $sdk"
