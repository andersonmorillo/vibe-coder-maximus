import sys
import types

import pytest

from voice_cursor.ports import MISSING
import voice_cursor.stt as stt
from voice_cursor.stt import (
    hot_needed,
    mic_device_index,
    mic_muted,
    resolve_stt_device,
    speech_gate,
)


def test_resolve_stt_device_cuda_when_present():
    assert resolve_stt_device(cuda_count=1, override="") == ("cuda", "float16")
    assert resolve_stt_device(cuda_count=0, override="") == ("cpu", "int8")


def test_cuda_device_count_requires_cublas(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(get_cuda_device_count=lambda: 1),
    )

    def missing_library(_name):
        raise OSError("libcublas missing")

    monkeypatch.setattr("ctypes.CDLL", missing_library)
    assert stt.cuda_device_count() == 0


def test_resolve_stt_device_override_cpu(monkeypatch):
    monkeypatch.delenv("VOICE_CURSOR_STT_COMPUTE", raising=False)
    assert resolve_stt_device(cuda_count=4, override="cpu") == ("cpu", "int8")
    assert resolve_stt_device(cuda_count=0, override="cuda") == ("cuda", "float16")


def test_mic_device_index_env(monkeypatch):
    monkeypatch.setenv("VOICE_CURSOR_MIC_DEVICE", "6")
    assert mic_device_index() == 6
    assert mic_device_index(2) == 2


def test_mic_muted_follows_tts(monkeypatch):
    monkeypatch.setattr("voice_cursor.tts.is_speaking", lambda: True)
    assert mic_muted() is True
    monkeypatch.setattr("voice_cursor.tts.is_speaking", lambda: False)
    assert mic_muted() is False


def test_get_whisper_model_returns_cached_instance(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(stt, "_model", sentinel)
    assert stt.get_whisper_model() is sentinel


def test_transcribe_audio_reads_whisperx_segments(monkeypatch):
    class FakeWhisperXModel:
        def transcribe(self, audio, *, batch_size, language):
            assert batch_size == 1
            assert language == "en"
            return {"segments": [{"text": " hello "}, {"text": "world"}]}

    monkeypatch.setattr(stt, "_model", FakeWhisperXModel())
    assert stt.transcribe_audio(object()) == "hello world"


def test_listen_once_returns_transcribed_speech(monkeypatch):
    class FakeListener:
        _error = None

        def __init__(self, *args, **kwargs) -> None:
            pass

        def wait_ready(self, timeout: float = 180) -> bool:
            return True

        def poll(self):
            return "hey cursor microphone test"

        def close(self) -> None:
            pass

    monkeypatch.setattr(stt, "WhisperListener", FakeListener)
    monkeypatch.setattr(stt, "describe_input_devices", lambda selected=None: "  [0] fake")
    assert stt.listen_once(timeout=1) == "hey cursor microphone test"


def test_echo_live_rewrites_then_finalizes(capsys):
    stt._echo_width = 0
    stt.echo_live("hey")
    stt.echo_live("hey cursor create a login", done=True)
    out = capsys.readouterr().out
    assert "you> hey" in out
    assert "you> hey cursor create a login" in out
    assert out.endswith("\n")


def test_speech_gate_hears_quiet_laptop_mic(monkeypatch):
    monkeypatch.delenv("VOICE_CURSOR_STT_THRESHOLD", raising=False)
    gate = speech_gate(1e-05)
    assert gate == 0.0008
    assert 0.002 > gate
    assert 0.00576 > gate
    assert gate < 0.012


def test_speech_gate_honors_explicit_threshold(monkeypatch):
    monkeypatch.setenv("VOICE_CURSOR_STT_THRESHOLD", "0.012")
    assert speech_gate(1e-05) == 0.012


def test_hot_needed_defaults_to_two(monkeypatch):
    monkeypatch.delenv("VOICE_CURSOR_STT_HOT_BLOCKS", raising=False)
    assert hot_needed() == 2


def test_listen_once_times_out_when_silent(monkeypatch):
    class SilentListener:
        _error = None

        def __init__(self, *args, **kwargs) -> None:
            pass

        def wait_ready(self, timeout: float = 180) -> bool:
            return True

        def poll(self):
            return MISSING

        def close(self) -> None:
            pass

    monkeypatch.setattr(stt, "WhisperListener", SilentListener)
    monkeypatch.setattr(stt, "describe_input_devices", lambda selected=None: "  [0] fake")
    with pytest.raises(TimeoutError):
        stt.listen_once(timeout=0.2)
