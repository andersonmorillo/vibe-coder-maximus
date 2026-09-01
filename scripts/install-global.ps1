# Put `voice-cursor` on PATH (Windows).
# Run from the repo:  powershell -File scripts\install-global.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Missing $py. From the repo run: python -m pip install -e `".[voice,talk]`""
}
$destDir = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$cmdPath = Join-Path $destDir "voice-cursor.cmd"
@(
    "@echo off"
    "setlocal"
    "`"$py`" -m voice_cursor %*"
) | Set-Content -Path $cmdPath -Encoding ascii
Write-Host "Installed $cmdPath"

$configDir = Join-Path $env:USERPROFILE ".voice-cursor"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$globalEnv = Join-Path $configDir ".env"
$repoEnv = Join-Path $root ".env"
$example = Join-Path $root ".env.example"
if (Test-Path $repoEnv) {
    Copy-Item $repoEnv $globalEnv -Force
    Write-Host "Updated $globalEnv from this repo .env (used from every repo)"
} elseif (-not (Test-Path $globalEnv) -and (Test-Path $example)) {
    Copy-Item $example $globalEnv
    Write-Host "Wrote $globalEnv from example. Add OPENROUTER_API_KEY."
} elseif (Test-Path $globalEnv) {
    Write-Host "Keeping existing $globalEnv"
}

Write-Host "Open a new terminal, then from any project:"
Write-Host "  voice-cursor start --text"
Write-Host "Talk key: $globalEnv  (a project .env overrides this)"
