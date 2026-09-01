import pytest

from voice_cursor.ports import MISSING
import voice_cursor.stt as stt
from voice_cursor.stt import mic_device_index, mic_muted, resolve_stt_device


def test_resolve_stt_device_cuda_when_present():
    assert resolve_stt_device(cuda_count=1, override="") == ("cuda", "float16")
    assert resolve_stt_device(cuda_count=0, override="") == ("cpu", "int8")


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
