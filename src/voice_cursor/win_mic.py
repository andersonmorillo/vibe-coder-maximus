"""Capture the Windows microphone from WSL via ffmpeg.exe DirectShow.

WSL Pulse/RDP devices are not the PC mic. ffmpeg.exe already talks to WASAPI/
DirectShow on the Windows side; Whisper stays in WSL.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass

SAMPLE_RATE = 16000

_QUOTED_DEVICE = re.compile(r'"([^"]+)"\s*\((audio|video)\)', re.I)
_ALT_NAME = re.compile(r'Alternative name\s+"([^"]+)"')


@dataclass(frozen=True)
class DShowDevice:
    name: str
    kind: str
    alt: str = ""

    @property
    def spec(self) -> str:
        ident = self.alt or self.name
        return f"audio={ident}"


def running_in_wsl() -> bool:
    if sys.platform == "win32":
        return False
    if os.environ.get("WSL_DISTRO_NAME", "").strip():
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def windows_ffmpeg() -> str | None:
    override = os.environ.get("VOICE_CURSOR_FFMPEG", "").strip()
    if override:
        return override
    return shutil.which("ffmpeg.exe")


def mic_backend() -> str:
    raw = os.environ.get("VOICE_CURSOR_MIC", "").strip().lower()
    if raw in ("linux", "pulse", "local", "wsl"):
        return "local"
    if raw in ("windows", "win", "ffmpeg"):
        return "windows"
    if running_in_wsl() and windows_ffmpeg():
        return "windows"
    return "local"


def parse_dshow_devices(text: str) -> list[DShowDevice]:
    devices: list[DShowDevice] = []
    for line in text.splitlines():
        match = _QUOTED_DEVICE.search(line)
        if match:
            devices.append(DShowDevice(name=match.group(1), kind=match.group(2).lower()))
            continue
        match = _ALT_NAME.search(line)
        if match and devices:
            last = devices[-1]
            devices[-1] = DShowDevice(name=last.name, kind=last.kind, alt=match.group(1))
    return devices


def parse_dshow_audio_devices(text: str) -> list[DShowDevice]:
    return [device for device in parse_dshow_devices(text) if device.kind == "audio"]


def dshow_list_text(ffmpeg: str) -> str:
    proc = subprocess.run(
        [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return (proc.stderr or "") + (proc.stdout or "")


def list_windows_mics() -> list[DShowDevice]:
    ffmpeg = windows_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg.exe not found. Install ffmpeg on Windows "
            "(winget install Gyan.FFmpeg) or use --text."
        )
    devices = parse_dshow_audio_devices(dshow_list_text(ffmpeg))
    if not devices:
        raise RuntimeError("no Windows microphone found via ffmpeg DirectShow")
    return devices


def pick_windows_mic(
    devices: list[DShowDevice], override: int | None = None
) -> DShowDevice:
    raw = "" if override is not None else os.environ.get("VOICE_CURSOR_MIC_DEVICE", "").strip()
    if override is None and raw:
        try:
            override = int(raw)
        except ValueError:
            key = raw.lower()
            for device in devices:
                if key in device.name.lower() or key in device.alt.lower():
                    return device
            names = ", ".join(device.name for device in devices)
            raise RuntimeError(
                f"no Windows microphone matching {raw!r}. Available: {names}"
            )
    if override is not None:
        if override < 0 or override >= len(devices):
            raise RuntimeError(
                f"Windows microphone index {override} is out of range "
                f"(0-{len(devices) - 1})"
            )
        return devices[override]
    return devices[0]


def ffmpeg_capture_command(ffmpeg: str, device: DShowDevice) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-f",
        "dshow",
        "-audio_buffer_size",
        "50",
        "-i",
        device.spec,
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]


def describe_windows_devices(selected: int | None = None) -> str:
    devices = list_windows_mics()
    pick = pick_windows_mic(devices, selected)
    lines = [
        "  capture: Windows microphone via ffmpeg.exe "
        "(WSL Pulse/RDP is not the PC mic)",
    ]
    for index, device in enumerate(devices):
        marks = []
        if device is pick:
            marks.append("selected")
        if index == 0 and selected is None and not os.environ.get(
            "VOICE_CURSOR_MIC_DEVICE", ""
        ).strip():
            marks.append("default")
        mark = f" ({', '.join(marks)})" if marks else ""
        lines.append(f"  [{index}] {device.name}{mark}")
    return "\n".join(lines)


class WindowsFfmpegMic:
    """sounddevice-shaped reader: context manager with read(frames) -> (array, overflow)."""

    def __init__(self, device: int | None = None) -> None:
        self._ffmpeg = windows_ffmpeg()
        if not self._ffmpeg:
            raise RuntimeError(
                "ffmpeg.exe not found. Install ffmpeg on Windows or use --text."
            )
        self._device = pick_windows_mic(list_windows_mics(), device)
        self._proc: subprocess.Popen[bytes] | None = None
        self._err: list[str] = []
        self._err_thread: threading.Thread | None = None

    def __enter__(self) -> WindowsFfmpegMic:
        self._proc = subprocess.Popen(
            ffmpeg_capture_command(self._ffmpeg, self._device),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._err_thread = threading.Thread(target=self._drain_err, daemon=True)
        self._err_thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

    def _drain_err(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self._err.append(line)

    def _fail(self, prefix: str) -> RuntimeError:
        detail = self._err[-1] if self._err else "ffmpeg exited"
        return RuntimeError(f"{prefix}: {detail}")

    def read(self, frames: int):
        import numpy as np

        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Windows microphone is not open")
        need = frames * 4
        buf = bytearray()
        while len(buf) < need:
            chunk = self._proc.stdout.read(need - len(buf))
            if not chunk:
                raise self._fail("Windows microphone closed")
            buf.extend(chunk)
        audio = np.frombuffer(bytes(buf), dtype=np.float32).copy()
        return audio.reshape(-1, 1), False
