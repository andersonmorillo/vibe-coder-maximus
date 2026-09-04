from __future__ import annotations

import os
import sys
import threading


class InterruptKey:
    """Background Enter-on-stdin tap to stop TTS and wait for the next utterance."""

    def __init__(self, key: str | None = None) -> None:
        self._key = (key or os.environ.get("VOICE_CURSOR_INTERRUPT_KEY", "enter")).strip().lower()
        self._pressed = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if self._enabled():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _enabled(self) -> bool:
        if self._key in ("off", "none", "false", "0"):
            return False
        return sys.stdin.isatty()

    def poll(self) -> bool:
        if not self._enabled():
            return False
        if self._pressed.is_set():
            self._pressed.clear()
            return True
        return False

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        import select

        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            except Exception:
                return
            if not ready:
                continue
            line = sys.stdin.readline()
            if line == "":
                return
            if self._key == "enter":
                self._pressed.set()
