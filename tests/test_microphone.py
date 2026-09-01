"""Hardware listen check for the real faster-whisper microphone listener.

Running this file alone uses the microphone:

    python -m pytest tests/test_microphone.py -s

The full suite skips it unless VOICE_CURSOR_REAL_MIC=1 or --run-mic.
"""

from __future__ import annotations

import pytest

from voice_cursor.stt import listen_once


@pytest.mark.real_mic
def test_real_microphone_hears_speech() -> None:
    heard = listen_once(timeout=45)
    assert heard.strip(), "transcription was empty"
    print(f"Heard: {heard}", flush=True)
