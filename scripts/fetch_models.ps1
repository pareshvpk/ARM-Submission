# scripts/fetch_models.ps1
# Download Linux CLI model assets from the phase1-submission GitHub release.
#
# Usage:
#   .\scripts\fetch_models.ps1 [[-ModelsDir] <destination_dir>]
# Default destination: ./models

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ModelsDir = "models"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

$tag = "phase1-submission"
$repo = "Vishnu-3727/ps3-sentinel"
$baseUrl = "https://github.com/$repo/releases/download/$tag"

Write-Host "=========================================================="
Write-Host "PS3 Sentinel: Fetch Linux / Linux Models"
Write-Host "=========================================================="
Write-Host ("Release: " + $baseUrl)
Write-Host ("Destination: " + $ModelsDir)
Write-Host ""

if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
}
$modelsPath = (Resolve-Path $ModelsDir).Path

$subDirs = @("url_v2", "sms_v6ml", "llama32_1b")
foreach ($sub in $subDirs) {
    $p = Join-Path $modelsPath $sub
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
    }
}

$hasGh = $false
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $hasGh = $true
}

function Download-Asset {
    param(
        [string]$AssetName,
        [string]$DestinationPath
    )
    Write-Host ("Downloading " + $AssetName + " -> " + $DestinationPath + "...")
    $downloaded = $false
    if ($hasGh) {
        try {
            $destDir = Split-Path -Parent $DestinationPath
            & gh release download $tag --repo $repo --pattern $AssetName --dir $destDir --clobber
            if ($LASTEXITCODE -eq 0) {
                $downloadedFile = Join-Path $destDir $AssetName
                if ($downloadedFile -ne $DestinationPath -and (Test-Path $downloadedFile)) {
                    Move-Item -Path $downloadedFile -Destination $DestinationPath -Force
                }
                $downloaded = $true
            }
        } catch {
            $downloaded = $false
        }
    }

    if (-not $downloaded) {
        $url = "$baseUrl/$AssetName"
        $curlCmd = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curlCmd) {
            & curl.exe -sSL -f -o $DestinationPath $url
            if ($LASTEXITCODE -ne 0) {
                Write-Error ("curl failed to download " + $url)
                exit 1
            }
        } else {
            Invoke-WebRequest -Uri $url -OutFile $DestinationPath
        }
    }

    if (-not (Test-Path $DestinationPath)) {
        Write-Error ("Failed to download asset: " + $AssetName)
        exit 1
    }
}

# 1. Download SHA256SUMS
$sumsFile = Join-Path $modelsPath "SHA256SUMS"
Download-Asset -AssetName "SHA256SUMS" -DestinationPath $sumsFile

$expectedHashes = @{}
foreach ($line in Get-Content $sumsFile) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
    $parts = $trimmed -split "\s+", 2
    if ($parts.Count -eq 2) {
        $hashVal = $parts[0].Trim().ToLowerInvariant()
        $fileName = $parts[1].Trim().TrimStart("*").Trim()
        $expectedHashes[$fileName] = $hashVal
    }
}

function Verify-FileHash {
    param(
        [string]$FilePath,
        [string]$AssetName
    )
    if (-not $expectedHashes.ContainsKey($AssetName)) {
        Write-Error ("Asset " + $AssetName + " not found in SHA256SUMS")
        exit 1
    }
    $expected = $expectedHashes[$AssetName]
    $actual = (Get-FileHash -Path $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Write-Error ("SHA256 mismatch for " + $AssetName + "`n  Expected: " + $expected + "`n  Actual:   " + $actual)
        exit 1
    }
    Write-Host ("  [OK] Verified " + $AssetName)
}

# 2. Download and verify each asset required by the Linux
# Assets mapping: AssetName -> Destination relative to modelsPath
$linuxAssets = @(
    @{ Asset = "url_cnn_v2.pte"; Dest = "url_v2/url_cnn_v2.pte" },
    @{ Asset = "vocab.json";      Dest = "url_v2/vocab.json" },
    @{ Asset = "sms_int8.pte";    Dest = "sms_v6ml/sms_int8.pte" },
    @{ Asset = "id_map.json";     Dest = "sms_v6ml/id_map.json" },
    @{ Asset = "llama.pte";       Dest = "llama32_1b/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte" },
    @{ Asset = "tokenizer.model"; Dest = "llama32_1b/tokenizer.model" }
)

foreach ($entry in $linuxAssets) {
    $asset = $entry["Asset"]
    $destRel = $entry["Dest"]
    $fullDest = Join-Path $modelsPath $destRel
    Download-Asset -AssetName $asset -DestinationPath $fullDest
    Verify-FileHash -FilePath $fullDest -AssetName $asset
}

# 3. Download and extract sms_tokenizer.zip into models/sms_v6ml/tokenizer
$tokenizerZip = Join-Path $modelsPath "sms_v6ml/sms_tokenizer.zip"
Download-Asset -AssetName "sms_tokenizer.zip" -DestinationPath $tokenizerZip
Verify-FileHash -FilePath $tokenizerZip -AssetName "sms_tokenizer.zip"

$tokDir = Join-Path $modelsPath "sms_v6ml/tokenizer"
if (Test-Path $tokDir) {
    Remove-Item -Path $tokDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tokDir -Force | Out-Null
Write-Host "Unzipping sms_tokenizer.zip into models/sms_v6ml/tokenizer..."
Expand-Archive -Path $tokenizerZip -DestinationPath $tokDir -Force
Remove-Item -Path $tokenizerZip -Force

Write-Host "All Linux models downloaded and verified successfully."
