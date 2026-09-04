# Spec: Interrupt-to-Listen (stop the agent while it is talking)

## Objective

When **voice-cursor** is speaking a reply (Windows SAPI TTS), the captain should be able to **interrupt immediately** so the session returns to listening. The same UX should feel natural in microphone mode: speak over the agent, and it stops talking and hears you next.

**User story:** “I asked a question. The agent is still talking. I want to cut it off and say something else without ending the session.”

**Out of scope for this slice:**

- Queueing a follow-up while apply is in flight (see `docs/interaction-plan.md` “Later”).
- GUI or push-to-talk hardware.
- Replacing Whisper with a different STT stack.

## Assumptions

1. Primary use is **microphone mode** (`voice-cursor start`, not `--text`).
2. TTS uses **Windows SAPI** via PowerShell (`SapiSpeaker`); `--no-tts` already avoids the problem.
3. The captain is on **WSL or native Windows** with the existing mic path (`WhisperListener`).
4. Interrupt should **not** end the session unless the captain says `stop listening` / `quit`.
5. Short backchannels (`yeah`, `ok`) must **not** interrupt TTS (same contract as during agent runs).
6. Echo from the speaker may be picked up by the mic; the design must tolerate false positives without transcribing the agent’s own voice as a new prompt.

→ Correct these now or we proceed with them.

## Current behavior (gap analysis)

| Phase | Can interrupt today? | Why |
| --- | --- | --- |
| Agent streaming (`talk> (working...)`) | **Mostly yes** | `loop.py` polls the mic queue while `iter_text()` runs; mic is **not** muted. |
| TTS playback (`cursor>` speaking) | **No (voice)** | `stt.mic_muted()` returns `tts.is_speaking()` and **drops all capture** while audio plays. `loop.py` polls an empty queue. |
| TTS playback | **Partial (commands)** | `be quiet` / `stop` are documented, but unreachable by voice during mute. |
| Text mode (`--text`) | **No** | `StdinListener` has no `poll()`; barge-in is mic-only. |

The barge-in loop in `loop.py` (lines 263–284) is correct; the microphone path never feeds it during speech.

## Tech stack

- Python 3.11–3.13, existing `voice-cursor` package (`src/voice_cursor/`)
- WhisperX + sounddevice / Windows ffmpeg mic (`stt.py`, `win_mic.py`)
- Windows SAPI TTS (`tts.py`)
- pytest for unit tests (no new dependencies)

## Commands

```sh
# Dev / test
cd vibe-coder-maximus
python -m pip install -e ".[dev,voice,talk]"
python -m pytest -q

# Manual check (mic + TTS)
python -m voice_cursor start

# Dry run (no API, no mic)
printf 'say hello\nquit\n' | python -m voice_cursor start --fake --text --no-tts
```

## Project structure

```
src/voice_cursor/
  loop.py          # session loop; barge-in during speech (already present)
  stt.py           # WhisperListener; mic_muted() gate (change here)
  tts.py           # SapiSpeaker.stop(), is_speaking()
  commands.py      # intent classification (minor: speaking-phase semantics)
  session.py       # Phase.SPEAKING (use for classify context)
  ports.py         # Listener / Speaker protocols
tests/
  test_loop.py     # barge-in tests (extend)
  test_stt.py      # interrupt-during-TTS unit tests (new)
docs/
  interaction-plan.md  # update “Gaps” when shipped
```

## Code style

Match existing module style: small functions, `MISSING` sentinel, no new abstractions unless they cross a real boundary.

```python
# Example: interrupt sentinel on the poll path (illustrative)
_INTERRUPT = object()

def poll(self):
    try:
        return self._q.get_nowait()
    except Empty:
        return MISSING
```

Prefer extending `WhisperListener` over a second mic thread.

## Testing strategy

| Level | What | How |
| --- | --- | --- |
| Unit | VAD-only path fires while `is_speaking()` mocked true | `test_stt.py` with fake audio blocks / monkeypatched `is_speaking` |
| Unit | Interrupt stops sticky speaker and returns to listen | Extend `test_loop.py` (`_StickySpeaker` pattern already exists) |
| Unit | Backchannel during TTS does not interrupt | `test_loop.py` with poll injection |
| Unit | `stop` during SPEAKING → quiet/cancel speech, not end session | `test_commands.py` + loop integration |
| Manual | Real mic + TTS | Captain speaks over agent; agent stops and transcribes next utterance |

No new pytest markers; hardware check remains optional.

## Boundaries

- **Always:** Run `python -m pytest -q` before landing; keep text-mode behavior unchanged unless explicitly extended; preserve wake-word filtering.
- **Ask first:** New CLI flags, new env vars, changing default interrupt sensitivity, keyboard interrupt in mic mode.
- **Never:** Commit API keys; add heavy deps (Porcupine, WebRTC AEC libs); transcribe the agent’s own TTS audio as a user prompt without an explicit interrupt.

## Proposed design

### 1. Duplex interrupt detection during TTS (primary)

While `tts.is_speaking()` is true, **do not fully mute** the mic. Instead:

1. Keep reading audio blocks in `WhisperListener._loop`.
2. Use a **higher RMS gate** than normal speech (`INTERRUPT_RATIO`, e.g. 6× noise floor, env-overridable) so quiet room noise and speaker bleed are ignored.
3. Require **2–3 consecutive hot blocks** (reuse `hot_needed()` pattern) before treating it as a captain interrupt.
4. On interrupt:
   - Call `SapiSpeaker.stop()` (or invoke a small callback registered by the session bootstrap).
   - Enqueue a **priority poll item** so `loop.py`’s existing `_barge_in_during` / `_playing` loop sees it immediately.
   - **Do not** transcribe audio captured during TTS playback (discard buffer); after `stop()`, fall through to normal utterance capture.

Classification of the interrupt utterance still happens **after** TTS stops, on the next full utterance (existing path).

### 2. Speaking-phase command semantics

Pass `speaking=True` (or `run_active=True` only during RUNNING) into `classify()` from the barge path:

| Say (during TTS) | Intent | Action |
| --- | --- | --- |
| `stop`, `cancel`, `never mind` | `CANCEL_RUN` or new `STOP_SPEECH` | Stop TTS; return to listen (do **not** end session) |
| `be quiet`, `silence` | `QUIET` | Stop TTS only |
| `yeah`, `ok`, … | `BACKCHANNEL` | Ignored (no interrupt) |
| anything else | `PROMPT` | Stop TTS; treat as next talk turn (existing `_barge`) |

Fix today’s footgun: bare `stop` with `run_active=False` ends the session; during `Phase.SPEAKING` it should stop speech, not quit.

### 3. Optional keyboard tap (secondary, same slice if cheap)

Background thread during TTS: **Enter** on stdin stops speech and signals listen. Useful when the room is noisy or the captain prefers not to shout. Off by default in mic mode unless `--interrupt-key` or env `VOICE_CURSOR_INTERRUPT_KEY=enter` is set.

### 4. Discoverability

- Spoken `help` line: add “speak over me to interrupt, or say be quiet.”
- README in-session table: clarify that voice interrupt works **while the agent is speaking**.

## Success criteria

- [ ] While TTS is playing in mic mode, captain speech above the interrupt gate stops playback within **~300 ms** (2–3 × 50 ms blocks + stop latency).
- [ ] After interrupt, the next full utterance is transcribed and handled normally (talk / apply / commands).
- [ ] Agent’s own TTS does **not** reliably trigger interrupt in a quiet room at default sensitivity (manual soak; unit tests use mocked levels).
- [ ] `yeah` / `ok` during TTS do not stop speech (regression test).
- [ ] `stop` during TTS stops speech and **does not** end the session.
- [ ] Existing barge-in during agent streaming remains green (`python -m pytest -q`).
- [ ] `docs/interaction-plan.md` “Gaps” updated; README command table updated.

## Open questions

**Resolved (captain, 2026-09-03):**

1. **Sensitivity:** fixed higher gate (`INTERRUPT_RATIO=6`, override via `VOICE_CURSOR_INTERRUPT_RATIO`).
2. **Keyboard interrupt:** included in v1 — Enter in mic mode when stdin is a TTY (`VOICE_CURSOR_INTERRUPT_KEY=off` to disable).
3. **After interrupt:** stop speech and **wait for the next full sentence** (`_LISTEN` → `next_utterance()`); the interrupt phrase is not treated as a talk turn.
4. **Interrupt trigger:** spoken commands only during TTS (`stop`, `be quiet`, `cancel`, etc.) — not arbitrary speech or wake-word-only.
