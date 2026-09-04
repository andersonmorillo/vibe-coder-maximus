from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue

from voice_cursor.ports import MISSING
from voice_cursor.win_mic import mic_backend

SAMPLE_RATE = 16000
# WhisperX-style: find speech relative to noise, then transcribe.
# A fixed 0.012 RMS gate missed this laptop mic (peaks ~0.002–0.006).
NOISE_RATIO = 4.0
NOISE_FLOOR = 0.0008
HOT_BLOCKS = 2
SILENCE_TAIL_S = 1.0
MAX_UTTERANCE_S = 30
MIN_SPEECH_S = 0.4
MODEL_SIZE = os.environ.get("VOICE_CURSOR_STT_MODEL", "base.en")
BLOCK_S = 0.05
PARTIAL_EVERY_S = float(os.environ.get("VOICE_CURSOR_STT_PARTIAL_S", "0.8"))


def configured_threshold() -> float | None:
    raw = os.environ.get("VOICE_CURSOR_STT_THRESHOLD", "").strip()
    if not raw:
        return None
    return float(raw)


def hot_needed() -> int:
    raw = os.environ.get("VOICE_CURSOR_STT_HOT_BLOCKS", "").strip()
    return int(raw) if raw else HOT_BLOCKS


def silence_tail_s() -> float:
    raw = os.environ.get("VOICE_CURSOR_STT_SILENCE", "").strip()
    return float(raw) if raw else SILENCE_TAIL_S


def speech_gate(noise_rms: float) -> float:
    """RMS above this counts as speech. Override with VOICE_CURSOR_STT_THRESHOLD."""
    fixed = configured_threshold()
    if fixed is not None:
        return fixed
    return max(float(noise_rms) * NOISE_RATIO, NOISE_FLOOR)


def update_noise(noise_rms: float, rms: float) -> float:
    return 0.95 * float(noise_rms) + 0.05 * float(rms)


_model = None
_model_lock = threading.Lock()
_transcribe_lock = threading.Lock()
_echo_lock = threading.Lock()
_echo_width = 0
_resolved: tuple[str, str, str] | None = None


def cuda_device_count() -> int:
    try:
        from ctranslate2 import get_cuda_device_count

        count = int(get_cuda_device_count() or 0)
        if count:
            import ctypes

            library = "cublas64_12.dll" if os.name == "nt" else "libcublas.so.12"
            ctypes.CDLL(library)
        return count
    except Exception:
        return 0


def resolve_stt_device(
    cuda_count: int | None = None, override: str | None = None
) -> tuple[str, str]:
    """Whisper device + compute type. CUDA float16 when a GPU is there."""
    raw = (
        os.environ.get("VOICE_CURSOR_STT_DEVICE", "")
        if override is None
        else override
    ).strip()
    compute_ov = os.environ.get("VOICE_CURSOR_STT_COMPUTE", "").strip()
    o = raw.lower()
    if o in ("cpu",):
        return "cpu", compute_ov or "int8"
    if o in ("cuda", "gpu") or o.startswith("cuda:"):
        return ("cuda" if o in ("cuda", "gpu") else raw), compute_ov or "float16"
    n = cuda_device_count() if cuda_count is None else cuda_count
    if n > 0:
        return "cuda", compute_ov or "float16"
    return "cpu", compute_ov or "int8"


def stt_model_name() -> str:
    return os.environ.get("VOICE_CURSOR_STT_MODEL", MODEL_SIZE)


def mic_device_index(override: int | None = None) -> int | None:
    if override is not None:
        return override
    raw = os.environ.get("VOICE_CURSOR_MIC_DEVICE", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def runtime_summary() -> str:
    model = stt_model_name()
    if _resolved is not None:
        device, compute, loaded = _resolved
        return f"WhisperX {loaded} on {device} ({compute})"
    device, compute = resolve_stt_device()
    return f"WhisperX {model} on {device} ({compute})"


def mic_muted() -> bool:
    """Drop capture while TTS is playing so the speaker is not transcribed."""
    try:
        from voice_cursor.tts import is_speaking

        return is_speaking()
    except Exception:
        return False


def get_whisper_model():
    """One WhisperModel per process. Reloading per utterance is too slow for a loop."""
    global _model, _resolved
    with _model_lock:
        if _model is None:
            try:
                import whisperx
            except ImportError as exc:
                raise RuntimeError(
                    "WhisperX is required for microphone input. "
                    'Install with: pip install -e ".[voice]"'
                ) from exc

            size = stt_model_name()
            device, compute = resolve_stt_device()
            cache = os.environ.get(
                "VOICE_CURSOR_STT_CACHE",
                str(Path.home() / ".voice-cursor" / "whisper"),
            )
            Path(cache).mkdir(parents=True, exist_ok=True)
            try:
                _model = whisperx.load_model(
                    size,
                    device=device,
                    compute_type=compute,
                    language="en",
                    vad_method="silero",
                    download_root=cache,
                )
                _resolved = (device, compute, size)
            except Exception:
                if device == "cpu":
                    raise
                print(
                    f"voice-cursor: Whisper {size} failed on {device}, using CPU int8",
                    flush=True,
                )
                _model = whisperx.load_model(
                    size,
                    device="cpu",
                    compute_type="int8",
                    language="en",
                    vad_method="silero",
                    download_root=cache,
                )
                _resolved = ("cpu", "int8", size)
        return _model


def transcribe_audio(audio) -> str:
    """Transcribe a float32 mono array at SAMPLE_RATE."""
    with _transcribe_lock:
        result = get_whisper_model().transcribe(audio, batch_size=1, language="en")
        segments = result.get("segments", []) if isinstance(result, dict) else result
        text: list[str] = []
        for segment in segments:
            value = (
                segment.get("text", "")
                if isinstance(segment, dict)
                else getattr(segment, "text", "")
            )
            if value:
                text.append(str(value).strip())
        return " ".join(text).strip()


def echo_live(text: str, *, done: bool = False) -> None:
    """Rewrite the current terminal line with the in-progress transcript."""
    global _echo_width
    line = "you> " + " ".join(text.split())
    with _echo_lock:
        pad = max(_echo_width - len(line), 0)
        _echo_width = len(line)
        print("\r" + line + (" " * pad), end="\n" if done else "", flush=True)
        if done:
            _echo_width = 0


class WhisperListener:
    """Continuous listener: adaptive VAD, then WhisperX ASR.

    One capture stream for VAD and audio. Nested streams fail on Windows.
    """

    def __init__(self, wake_word: str = "", device: int | None = None) -> None:
        import whisperx  # noqa: F401 — fail fast if extras missing

        if mic_backend() != "windows":
            import sounddevice  # noqa: F401

        self.wake_word = wake_word
        self.device = device if mic_backend() == "windows" else mic_device_index(device)
        self.echoes_input = True
        self._q: Queue[str | None] = Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: str | None = None
        self._capture = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 180) -> bool:
        if not self._ready.wait(timeout):
            return False
        return self._error is None

    def next_utterance(self) -> str | None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.25)
            except Empty:
                continue
            return item
        return None

    def poll(self):
        try:
            return self._q.get_nowait()
        except Empty:
            return MISSING

    def close(self) -> None:
        self._stop.set()
        capture = self._capture
        if capture is not None:
            closer = getattr(capture, "close", None)
            if closer is not None:
                closer()
        self._q.put(None)
        self._thread.join(timeout=2)

    def _warmup(self) -> None:
        get_whisper_model()

    def _finish_utterance(self, stream, prefix: list, *, gate: float) -> object:
        import numpy as np

        block_n = int(SAMPLE_RATE * BLOCK_S)
        chunks = list(prefix)
        silent = 0.0
        started = time.time()
        last_partial = 0.0
        tail = silence_tail_s()
        partial_thread: threading.Thread | None = None
        echo_live("…")

        def _kick_partial(snap) -> None:
            nonlocal partial_thread

            def _run() -> None:
                try:
                    text = transcribe_audio(snap)
                    if text and not self._stop.is_set():
                        echo_live(text, done=False)
                except Exception:
                    pass

            partial_thread = threading.Thread(target=_run, daemon=True)
            partial_thread.start()

        while time.time() - started < MAX_UTTERANCE_S and not self._stop.is_set():
            data, _ = stream.read(block_n)
            mono = data[:, 0] if data.ndim > 1 else data
            if mic_muted():
                silent += BLOCK_S
                if silent >= tail:
                    break
                continue
            chunks.append(mono.copy())
            rms = float((mono**2).mean() ** 0.5)
            if rms > gate:
                silent = 0.0
            else:
                silent += BLOCK_S
                if silent >= tail:
                    break
            now = time.time()
            if now - last_partial >= PARTIAL_EVERY_S:
                audio_so_far = np.concatenate(chunks)
                if len(audio_so_far) >= SAMPLE_RATE * MIN_SPEECH_S and (
                    partial_thread is None or not partial_thread.is_alive()
                ):
                    _kick_partial(audio_so_far.copy())
                    last_partial = now
        if partial_thread is not None:
            partial_thread.join(timeout=2)
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if len(audio) < SAMPLE_RATE * MIN_SPEECH_S:
            return None
        return audio

    def _loop(self) -> None:
        stream_cm = None
        stream = None
        try:
            self._warmup()
            stream_cm = open_mic_stream(self.device)
            stream = stream_cm.__enter__()
            self._capture = stream_cm
        except Exception as exc:
            self._error = str(exc)
            self._q.put(None)
            print(f"voice-cursor: STT failed to load ({exc}). Use --text.")
            return
        finally:
            self._ready.set()

        block_n = int(SAMPLE_RATE * BLOCK_S)
        run = 0
        tail: deque = deque(maxlen=8)
        noise = NOISE_FLOOR
        need = hot_needed()
        try:
            while not self._stop.is_set():
                data, _ = stream.read(block_n)
                mono = data[:, 0] if data.ndim > 1 else data
                tail.append(mono.copy())
                rms = float((mono**2).mean() ** 0.5)
                gate = speech_gate(noise)
                if rms > gate:
                    run += 1
                else:
                    noise = update_noise(noise, rms)
                    run = 0
                    continue
                if mic_muted():
                    run = 0
                    tail.clear()
                    continue
                if run < need:
                    continue
                run = 0
                audio = self._finish_utterance(stream, list(tail), gate=gate)
                tail.clear()
                if audio is None:
                    continue
                text = transcribe_audio(audio)
                if text:
                    echo_live(text, done=True)
                    self._q.put(text)
        except Exception as exc:
            if not self._stop.is_set():
                print(f"voice-cursor: STT loop ended ({exc})")
            self._q.put(None)
        finally:
            self._capture = None
            if stream_cm is not None:
                stream_cm.__exit__(None, None, None)


def open_mic_stream(device: int | None):
    if mic_backend() == "windows":
        from voice_cursor.win_mic import WindowsFfmpegMic

        return WindowsFfmpegMic(device)
    import sounddevice as sd

    block_n = int(SAMPLE_RATE * BLOCK_S)
    return sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=block_n,
        device=mic_device_index(device),
    )


def describe_input_devices(selected: int | None = None) -> str:
    if mic_backend() == "windows":
        from voice_cursor.win_mic import describe_windows_devices

        return describe_windows_devices(selected)
    import sounddevice as sd
    from voice_cursor.win_mic import running_in_wsl, windows_ffmpeg

    default = sd.default.device
    default_in = default[0] if isinstance(default, (list, tuple)) else default
    pick = mic_device_index(selected)
    lines: list[str] = []
    if running_in_wsl():
        hint = (
            "install ffmpeg on Windows (winget install Gyan.FFmpeg)"
            if not windows_ffmpeg()
            else "unset VOICE_CURSOR_MIC=linux"
        )
        lines.append(
            f"  (WSL Pulse/RDP is not the PC mic. {hint} or use --text)"
        )
    for i, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"] or 0) <= 0:
            continue
        marks = []
        if i == default_in:
            marks.append("default")
        if pick is not None and i == pick:
            marks.append("selected")
        mark = f" ({', '.join(marks)})" if marks else ""
        lines.append(f"  [{i}] {device['name']}{mark}")
    return "\n".join(lines) or "  (no input devices)"


def listen_once(*, timeout: float = 45, device: int | None = None) -> str:
    """Open the real mic, wait for one transcribed utterance, then close.

    Raises RuntimeError if STT cannot start, TimeoutError if nothing is heard.
    """
    listener = WhisperListener(device=device)
    try:
        if not listener.wait_ready(timeout=180):
            raise RuntimeError(listener._error or "speech recognition did not start")
        print("Input devices:", flush=True)
        print(describe_input_devices(device), flush=True)
        print(f"Transcribing with {runtime_summary()}.", flush=True)
        print("Speak one short sentence now, then pause...", flush=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            heard = listener.poll()
            if heard is MISSING:
                time.sleep(0.1)
                continue
            if heard is None:
                raise RuntimeError(listener._error or "microphone listener stopped")
            text = str(heard).strip()
            if text:
                return text
        raise TimeoutError(
            f"no speech transcribed in {int(timeout)} seconds "
            "(check the default input device and speak louder)"
        )
    finally:
        listener.close()
