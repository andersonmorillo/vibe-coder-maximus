import pytest

from voice_cursor.ports import MISSING
import voice_cursor.stt as stt


def test_get_whisper_model_returns_cached_instance(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(stt, "_model", sentinel)
    assert stt.get_whisper_model() is sentinel


def test_listen_once_returns_transcribed_speech(monkeypatch):
    class FakeListener:
        _error = None

        def wait_ready(self, timeout: float = 180) -> bool:
            return True

        def poll(self):
            return "hey cursor microphone test"

        def close(self) -> None:
            pass

    monkeypatch.setattr(stt, "WhisperListener", FakeListener)
    monkeypatch.setattr(stt, "describe_input_devices", lambda: "  [0] fake")
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

        def wait_ready(self, timeout: float = 180) -> bool:
            return True

        def poll(self):
            return MISSING

        def close(self) -> None:
            pass

    monkeypatch.setattr(stt, "WhisperListener", SilentListener)
    monkeypatch.setattr(stt, "describe_input_devices", lambda: "  [0] fake")
    with pytest.raises(TimeoutError):
        stt.listen_once(timeout=0.2)
