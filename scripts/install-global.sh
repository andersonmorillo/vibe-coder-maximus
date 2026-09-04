#!/usr/bin/env bash
# Put `voice-cursor` on PATH (user-local npm, no sudo).
# Run from anywhere:  bash /path/to/vibe-coder-maximus/scripts/install-global.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
prefix="${NPM_CONFIG_PREFIX:-$HOME/.local}"
mkdir -p "$prefix"
npm install -g --prefix "$prefix" "$root"
bin="$prefix/bin/voice-cursor"
if [[ ":$PATH:" != *":$prefix/bin:"* ]]; then
  echo "voice-cursor: add this to your shell rc, then open a new terminal:"
  echo "  export PATH=\"$prefix/bin:\$PATH\""
fi
echo "Installed $bin"
echo "From any project:  voice-cursor --text --no-tts"
echo "Or:                npx --prefix $prefix voice-cursor --text --no-tts"

# Windows cmd resolves a different file: %USERPROFILE%\.local\bin\voice-cursor.cmd
# Default `wsl.exe` may be another distro, so pin this home's distro.
win_user="/mnt/c/Users/${USER}"
if [[ -d "$win_user" ]]; then
  mkdir -p "$win_user/.local/bin"
  distro="${WSL_DISTRO_NAME:-Ubuntu}"
  linux_bin="$prefix/bin/voice-cursor"
  {
    printf '@echo off\r\n'
    printf 'setlocal\r\n'
    printf 'set WSLENV=USERPROFILE/p:%%WSLENV%%\r\n'
    printf 'wsl.exe -d %s --cd "%%CD%%" -e %s %%*\r\n' "$distro" "$linux_bin"
  } > "$win_user/.local/bin/voice-cursor.cmd"
  echo "Windows cmd shim: C:\\Users\\${USER}\\.local\\bin\\voice-cursor.cmd (distro $distro)"
fi
