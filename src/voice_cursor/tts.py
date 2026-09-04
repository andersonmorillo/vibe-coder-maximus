from __future__ import annotations

import shutil
import subprocess
import sys
import threading

_lock = threading.Lock()
_speaking = 0
_active_speaker: SapiSpeaker | None = None


def is_speaking() -> bool:
    """True only while TTS is actually playing. Poll so mute cannot stick."""
    speaker = _active_speaker
    if speaker is not None:
        return speaker.is_playing()
    return _speaking > 0


def _inc() -> None:
    global _speaking
    with _lock:
        _speaking += 1


def _dec() -> None:
    global _speaking
    with _lock:
        _speaking = max(0, _speaking - 1)


def _escape_ps(text: str) -> str:
    return text.replace("'", "''")


def _sapi_command(text: str) -> str:
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 2; "
        f"$s.Speak('{_escape_ps(text)}')"
    )


def _powershell_bin() -> str | None:
    if sys.platform == "win32":
        return shutil.which("powershell") or shutil.which("powershell.exe")
    return shutil.which("powershell.exe")


class SapiSpeaker:
    """Windows SAPI via PowerShell. say() is non-blocking; stop() kills the child."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._counted = False

    def say(self, text: str) -> None:
        self.stop()
        if not text.strip():
            return
        powershell = _powershell_bin()
        if not powershell:
            print(f"cursor> {text}")
            return
        self._proc = subprocess.Popen(
            [powershell, "-NoProfile", "-Command", _sapi_command(text)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        global _active_speaker
        _active_speaker = self
        _inc()
        self._counted = True

    def is_playing(self) -> bool:
        if self._proc is None:
            return False
        if self._proc.poll() is None:
            return True
        self._proc = None
        self._clear_count()
        return False

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._clear_count()

    def _clear_count(self) -> None:
        if self._counted:
            _dec()
            self._counted = False
