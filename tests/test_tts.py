import subprocess
import sys

from voice_cursor.tts import SapiSpeaker, _escape_ps


def test_escape_ps_doubles_quotes():
    assert _escape_ps("it's") == "it''s"


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
