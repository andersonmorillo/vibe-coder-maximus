# Put `voice-cursor` on PATH (Windows cmd / PowerShell).
# Delegates to the WSL install. Run the bash installer first:
#   bash scripts/install-global.sh
# Then:  powershell -File scripts\install-global.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$destDir = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$cmdPath = Join-Path $destDir "voice-cursor.cmd"
$distro = if ($env:WSL_DISTRO_NAME) { $env:WSL_DISTRO_NAME } else { "Ubuntu" }
$linuxBin = (wsl.exe -d $distro -e bash -c 'printf %s "$HOME/.local/bin/voice-cursor"').Trim()
if (-not $linuxBin) {
    throw "Could not resolve the WSL voice-cursor binary. Run bash scripts/install-global.sh first."
}
@(
    "@echo off"
    "setlocal"
    "set WSLENV=USERPROFILE/p:%WSLENV%"
    "wsl.exe -d $distro --cd `"%CD%`" -e $linuxBin %*"
) | Set-Content -Path $cmdPath -Encoding ascii
Write-Host "Installed $cmdPath -> $distro $linuxBin"

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
