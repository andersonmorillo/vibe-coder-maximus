import pytest

from voice_cursor.win_mic import (
    ffmpeg_capture_command,
    mic_backend,
    parse_dshow_audio_devices,
    pick_windows_mic,
)


FFMPEG_LIST = """
[in#0 @ 000001ac56620680] "HP Wide Vision HD Camera" (video)
[in#0 @ 000001ac56620680]   Alternative name "@device_pnp_\\\\?\\usb#vid_04f2"
[in#0 @ 000001ac56620680] "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)" (audio)
[in#0 @ 000001ac56620680]   Alternative name "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\\wave_{BC225C08-BFB6-47FA-8993-44C3453A9D0B}"
Error opening input file dummy.
"""


def test_parse_dshow_audio_uses_alternative_name():
    devices = parse_dshow_audio_devices(FFMPEG_LIST)
    assert len(devices) == 1
    assert "Microphone Array" in devices[0].name
    assert devices[0].spec.startswith("audio=@device_cm_")
    assert "HP Wide Vision" not in devices[0].name


def test_pick_windows_mic_by_index_and_name():
    devices = parse_dshow_audio_devices(FFMPEG_LIST)
    assert pick_windows_mic(devices, 0) is devices[0]
    assert pick_windows_mic(devices).name.startswith("Microphone Array")
    with pytest.raises(RuntimeError, match="out of range"):
        pick_windows_mic(devices, 3)


def test_pick_windows_mic_name_from_env(monkeypatch):
    devices = parse_dshow_audio_devices(FFMPEG_LIST)
    monkeypatch.setenv("VOICE_CURSOR_MIC_DEVICE", "microphone array")
    assert pick_windows_mic(devices) is devices[0]


def test_ffmpeg_capture_command_uses_dshow_spec():
    device = parse_dshow_audio_devices(FFMPEG_LIST)[0]
    command = ffmpeg_capture_command("/ffmpeg.exe", device)
    assert command[0] == "/ffmpeg.exe"
    assert command[command.index("-f") + 1] == "dshow"
    assert device.spec in command
    assert command[-2:] == ["f32le", "pipe:1"]


def test_mic_backend_uses_windows_ffmpeg_in_wsl(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.delenv("VOICE_CURSOR_MIC", raising=False)
    monkeypatch.setattr(
        "voice_cursor.win_mic.windows_ffmpeg", lambda: "/ffmpeg.exe"
    )
    assert mic_backend() == "windows"
    monkeypatch.setenv("VOICE_CURSOR_MIC", "linux")
    assert mic_backend() == "local"


def test_mic_backend_stays_local_without_ffmpeg(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.delenv("VOICE_CURSOR_MIC", raising=False)
    monkeypatch.setattr("voice_cursor.win_mic.windows_ffmpeg", lambda: None)
    assert mic_backend() == "local"


def test_windows_ffmpeg_mic_read_reshapes_float32(monkeypatch):
    np = pytest.importorskip("numpy")
    from voice_cursor.win_mic import WindowsFfmpegMic

    payload = (np.array([0.1, -0.2, 0.3], dtype=np.float32)).tobytes()

    class FakeStdout:
        def __init__(self) -> None:
            self._data = payload

        def read(self, n: int) -> bytes:
            chunk, self._data = self._data[:n], self._data[n:]
            return chunk

        def close(self) -> None:
            pass

    class Closed:
        def close(self) -> None:
            pass

        def __iter__(self):
            return iter(())

    class FakeProc:
        stdout = FakeStdout()
        stderr = Closed()

        def poll(self):
            return 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        "voice_cursor.win_mic.windows_ffmpeg", lambda: "/ffmpeg.exe"
    )
    monkeypatch.setattr(
        "voice_cursor.win_mic.list_windows_mics",
        lambda: parse_dshow_audio_devices(FFMPEG_LIST),
    )
    monkeypatch.setattr(
        "voice_cursor.win_mic.subprocess.Popen",
        lambda *args, **kwargs: FakeProc(),
    )
    with WindowsFfmpegMic(0) as mic:
        data, overflow = mic.read(3)
    assert overflow is False
    assert data.shape == (3, 1)
    assert abs(float(data[0, 0]) - 0.1) < 1e-6
