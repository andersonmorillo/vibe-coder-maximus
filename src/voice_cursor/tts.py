from __future__ import annotations

import subprocess
import sys
import threading

_lock = threading.Lock()
_speaking = 0


def is_speaking() -> bool:
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


class SapiSpeaker:
    """Windows SAPI via PowerShell. say() is non-blocking; stop() kills the child."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._counted = False

    def say(self, text: str) -> None:
        self.stop()
        if not text.strip():
            return
        if sys.platform != "win32":
            print(f"cursor> {text}")
            return
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{_escape_ps(text)}')"
        )
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
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
