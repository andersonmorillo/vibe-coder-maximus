import subprocess
import sys

from voice_cursor.tts import SapiSpeaker, _escape_ps, _powershell_bin, _sapi_command


def test_escape_ps_doubles_quotes():
    assert _escape_ps("it's") == "it''s"


def test_sapi_command_sets_rate_then_speaks():
    script = _sapi_command("hello")
    assert "$s.Rate = 2; " in script
    assert "$s.Speak('hello')" in script
    assert "2$s.Speak" not in script


def test_powershell_bin_uses_powershell_exe_off_windows(monkeypatch):
    monkeypatch.setattr("voice_cursor.tts.sys.platform", "linux")
    monkeypatch.setattr(
        "voice_cursor.tts.shutil.which",
        lambda name: "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        if name == "powershell.exe"
        else None,
    )
    assert _powershell_bin().endswith("powershell.exe")


def test_wsl_speaks_through_windows_powershell(monkeypatch):
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, command, **kwargs):
            calls.append(list(command))

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("voice_cursor.tts.sys.platform", "linux")
    monkeypatch.setattr(
        "voice_cursor.tts.shutil.which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr("voice_cursor.tts.subprocess.Popen", FakePopen)
    speaker = SapiSpeaker()
    speaker.say("hello")
    assert calls[0][:3] == ["powershell.exe", "-NoProfile", "-Command"]
    assert "Speak('hello')" in calls[0][-1]
    speaker.stop()


def test_no_powershell_prints_instead_of_speaking(monkeypatch, capsys):
    monkeypatch.setattr("voice_cursor.tts.sys.platform", "linux")
    monkeypatch.setattr("voice_cursor.tts.shutil.which", lambda name: None)
    SapiSpeaker().say("hello")
    assert "cursor> hello" in capsys.readouterr().out


def test_is_speaking_unmutes_after_powershell_exits(monkeypatch):
    from voice_cursor.tts import is_speaking

    class FakePopen:
        def __init__(self, command, **kwargs):
            pass

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(
        "voice_cursor.tts.shutil.which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr("voice_cursor.tts.subprocess.Popen", FakePopen)
    speaker = SapiSpeaker()
    speaker.say("hello")
    assert is_speaking() is False
    speaker.stop()


def test_stop_kills_sleeping_child():
    if sys.platform != "win32":
        return
    speaker = SapiSpeaker()
    speaker._proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", "Start-Sleep -Seconds 30"]
    )
    speaker._counted = True
    from voice_cursor import tts as ttsmod

    ttsmod._speaking = 1
    speaker.stop()
    assert speaker._proc is None
    assert ttsmod.is_speaking() is False
