from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue

from voice_cursor.ports import MISSING

SAMPLE_RATE = 16000
SPEECH_RMS = float(os.environ.get("VOICE_CURSOR_STT_THRESHOLD", "0.012"))
SILENCE_TAIL_S = 1.2
MAX_UTTERANCE_S = 30
MIN_SPEECH_S = 0.4
MODEL_SIZE = os.environ.get("VOICE_CURSOR_STT_MODEL", "base.en")
BLOCK_S = 0.05
PARTIAL_EVERY_S = float(os.environ.get("VOICE_CURSOR_STT_PARTIAL_S", "0.8"))

_model = None
_model_lock = threading.Lock()
_transcribe_lock = threading.Lock()
_echo_lock = threading.Lock()
_echo_width = 0


def get_whisper_model():
    """One WhisperModel per process. Reloading per utterance is too slow for a loop."""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            size = os.environ.get("VOICE_CURSOR_STT_MODEL", MODEL_SIZE)
            device = os.environ.get("VOICE_CURSOR_STT_DEVICE", "cpu")
            compute = "int8" if device == "cpu" else "float16"
            cache = os.environ.get(
                "VOICE_CURSOR_STT_CACHE",
                str(Path.home() / ".voice-cursor" / "whisper"),
            )
            Path(cache).mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(
                size, device=device, compute_type=compute, download_root=cache
            )
        return _model


def transcribe_audio(audio) -> str:
    """Transcribe a float32 mono array at SAMPLE_RATE."""
    with _transcribe_lock:
        segments, _ = get_whisper_model().transcribe(audio, language="en")
        return " ".join(s.text.strip() for s in segments).strip()


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
    """Continuous faster-whisper listener (Hearth listen.py loop, trimmed).

    One PortAudio stream for VAD and capture. Nested streams fail on Windows.
    Source pattern: https://github.com/0pen-Sourcer/Hearth/blob/main/hearth/listen.py
    """

    def __init__(self, wake_word: str = "") -> None:
        import faster_whisper  # noqa: F401 — fail fast if extras missing
        import sounddevice  # noqa: F401

        self.wake_word = wake_word
        self.echoes_input = True
        self._q: Queue[str | None] = Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: str | None = None
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
        self._q.put(None)
        self._thread.join(timeout=2)

    def _warmup(self) -> None:
        get_whisper_model()

    def _finish_utterance(self, stream, prefix: list) -> object:
        import numpy as np

        block_n = int(SAMPLE_RATE * BLOCK_S)
        chunks = list(prefix)
        silent = 0.0
        started = time.time()
        last_partial = 0.0
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
            chunks.append(mono.copy())
            rms = float((mono**2).mean() ** 0.5)
            if rms > SPEECH_RMS:
                silent = 0.0
            else:
                silent += BLOCK_S
                if silent >= SILENCE_TAIL_S:
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
        try:
            self._warmup()
        except Exception as exc:
            self._error = str(exc)
            self._q.put(None)
            print(f"voice-cursor: STT failed to load ({exc}). Use --text.")
            return
        finally:
            self._ready.set()
        import sounddevice as sd

        block_n = int(SAMPLE_RATE * BLOCK_S)
        run = 0
        tail: deque = deque(maxlen=8)
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=block_n
            ) as stream:
                while not self._stop.is_set():
                    data, _ = stream.read(block_n)
                    mono = data[:, 0] if data.ndim > 1 else data
                    tail.append(mono.copy())
                    rms = float((mono**2).mean() ** 0.5)
                    if rms > SPEECH_RMS:
                        run += 1
                    else:
                        run = 0
                        continue
                    try:
                        from voice_cursor.tts import is_speaking

                        if is_speaking() and rms < SPEECH_RMS * 5:
                            run = 0
                            continue
                    except Exception:
                        pass
                    if run < 4:
                        continue
                    run = 0
                    audio = self._finish_utterance(stream, list(tail))
                    tail.clear()
                    if audio is None:
                        continue
                    text = transcribe_audio(audio)
                    if text:
                        echo_live(text, done=True)
                        self._q.put(text)
        except Exception as exc:
            print(f"voice-cursor: STT loop ended ({exc})")
            self._q.put(None)


def describe_input_devices() -> str:
    import sounddevice as sd

    default = sd.default.device
    default_in = default[0] if isinstance(default, (list, tuple)) else default
    lines: list[str] = []
    for i, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"] or 0) <= 0:
            continue
        mark = " (default)" if i == default_in else ""
        lines.append(f"  [{i}] {device['name']}{mark}")
    return "\n".join(lines) or "  (no input devices)"


def listen_once(*, timeout: float = 45) -> str:
    """Open the real mic, wait for one transcribed utterance, then close.

    Raises RuntimeError if STT cannot start, TimeoutError if nothing is heard.
    """
    listener = WhisperListener()
    try:
        if not listener.wait_ready(timeout=180):
            raise RuntimeError(listener._error or "speech recognition did not start")
        print("Input devices:", flush=True)
        print(describe_input_devices(), flush=True)
        print(
            f"Transcribing with faster-whisper {os.environ.get('VOICE_CURSOR_STT_MODEL', MODEL_SIZE)}.",
            flush=True,
        )
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
