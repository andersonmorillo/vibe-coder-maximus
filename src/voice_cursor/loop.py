from __future__ import annotations

import sys
import time
from pathlib import Path

from voice_cursor.commands import (
    HELP_SPEECH,
    Intent,
    classify,
    is_background,
    is_speech_interrupt,
)
from voice_cursor.ports import MISSING, CodingAgent, Listener, Speaker
from voice_cursor.session import Session
from voice_cursor.speakable import speakable, spoken_preview
from voice_cursor.spec import clear_spec, read_spec, write_spec

VOICE_INSTRUCTION = (
    "You are driven by a voice interface. Keep the final assistant message "
    "to 2-4 short spoken sentences. Put all code in files. Do not dump diffs "
    "or code fences in the reply."
)

APPLY_PROMPT = (
    "Implement the change specified in .voice-cursor/request.md. "
    "Put all code in files. Do not dump diffs or code fences in the reply. "
    "Keep the final assistant message to 2-4 short spoken sentences."
)

_STOP = object()
_LISTEN = object()


def _poll(listener: Listener):
    poll = getattr(listener, "poll", None)
    if poll is None:
        return MISSING
    return poll()


def _playing(speaker: Speaker) -> bool:
    playing = getattr(speaker, "is_playing", None)
    return bool(playing()) if playing else False


def _speak(
    speaker: Speaker,
    text: str,
    *,
    echo: bool = True,
    session: Session | None = None,
) -> None:
    try:
        speaker.say(text, echo=echo)  # type: ignore[call-arg]
    except TypeError:
        speaker.say(text)
    if session is not None and text:
        session.last_spoken = text


def _reap(run) -> None:
    if run is None:
        return
    try:
        run.wait()
    except Exception:
        pass


def _barge_in_during(
    listener: Listener, *, wake_word: str, speaking: bool = False
):
    barge = _poll(listener)
    if barge is MISSING:
        return MISSING
    intent, _ = classify(
        barge,
        run_active=True,
        speaking=speaking,
        wake_word=wake_word,
    )
    if is_background(intent):
        return MISSING
    if speaking and intent is Intent.PROMPT:
        return MISSING
    if speaking and not is_speech_interrupt(intent) and intent is not Intent.STOP_SESSION:
        return MISSING
    return barge


def _stop_speech_and_listen(
    *,
    speaker: Speaker,
    session: Session,
    current,
) -> object:
    if current is not None:
        current.cancel()
        _reap(current)
    speaker.stop()
    session.end_turn()
    return _LISTEN


def _barge(
    barge,
    *,
    current,
    speaker: Speaker,
    session: Session,
    wake_word: str,
    speaking: bool = False,
):
    intent_b, _ = classify(
        barge,
        run_active=True,
        speaking=speaking,
        wake_word=wake_word,
    )
    if speaking and is_speech_interrupt(intent_b):
        return _stop_speech_and_listen(
            speaker=speaker, session=session, current=current
        )
    if current is not None:
        current.cancel()
        _reap(current)
    speaker.stop()
    session.end_turn()
    if intent_b is Intent.STOP_SESSION:
        session.stop()
        return _STOP
    if intent_b in (Intent.CANCEL_RUN, Intent.QUIET, Intent.IGNORE, Intent.BACKCHANNEL):
        return _LISTEN
    return barge


def _status_speech(spec_root: str | Path) -> str:
    spec_text = read_spec(spec_root)
    if not spec_text:
        return "No pending change. Talk to plan one, then say apply."
    return f"Pending change: {spoken_preview(spec_text)}"


def run_session(
    *,
    listener: Listener,
    speaker: Speaker,
    agent: CodingAgent,
    talk: CodingAgent,
    spec_root: str | Path = ".",
    wake_word: str = "",
    interrupt_key: object | None = None,
) -> None:
    session = Session()
    current = None
    heard = listener.next_utterance()
    if interrupt_key is None and getattr(listener, "echoes_input", False):
        from voice_cursor.interrupt_key import InterruptKey

        interrupt_key = InterruptKey()
    try:
        while session.is_open:
            if heard is None:
                session.stop()
                break
            intent, payload = classify(
                heard,
                run_active=session.run_active,
                speaking=session.speaking,
                wake_word=wake_word,
            )
            if is_background(intent):
                heard = listener.next_utterance()
                continue
            if intent is Intent.STOP_SESSION:
                if current is not None:
                    current.cancel()
                    _reap(current)
                speaker.stop()
                session.stop()
                break
            if intent is Intent.QUIET:
                speaker.stop()
                heard = listener.next_utterance()
                continue
            if intent is Intent.CANCEL_RUN:
                if current is not None:
                    current.cancel()
                    _reap(current)
                speaker.stop()
                session.end_turn()
                current = None
                heard = listener.next_utterance()
                continue
            if intent is Intent.HELP:
                _speak(speaker, HELP_SPEECH, session=session)
                heard = listener.next_utterance()
                continue
            if intent is Intent.STATUS:
                _speak(speaker, _status_speech(spec_root), session=session)
                heard = listener.next_utterance()
                continue
            if intent is Intent.REPEAT:
                text = session.last_spoken or "Nothing to repeat."
                _speak(speaker, text, session=session)
                heard = listener.next_utterance()
                continue
            if intent is Intent.CLEAR:
                dropped = clear_spec(spec_root)
                text = (
                    "Dropped the pending change."
                    if dropped
                    else "Nothing to drop."
                )
                _speak(speaker, text, session=session)
                heard = listener.next_utterance()
                continue
            if current is not None and session.run_active:
                current.cancel()
                _reap(current)
                speaker.stop()
            if intent is Intent.APPLY:
                if payload:
                    write_spec(spec_root, payload)
                spec_text = read_spec(spec_root)
                if not spec_text:
                    _speak(speaker, "Nothing to apply.", session=session)
                    heard = listener.next_utterance()
                    continue
                preview = spoken_preview(spec_text)
                apply_message = getattr(agent, "apply_message", "Applying.")
                print(f"apply> {spec_text}", flush=True)
                _speak(speaker, f"{apply_message} {preview}", session=session)
                prompt = (
                    spec_text
                    if getattr(agent, "uses_request_text", False)
                    else APPLY_PROMPT
                )
                worker: CodingAgent = agent
                label = "firstmate" if getattr(agent, "uses_request_text", False) else "cursor"
            else:
                prompt = payload
                worker = talk
                label = "talk"
            session.begin_run()
            if not getattr(listener, "echoes_input", False):
                print(f"you> {payload}", flush=True)
            print(f"{label}> (working...)", flush=True)
            try:
                current = worker.send(prompt)
                chunks: list[str] = []
                barge = MISSING
                streamed = False
                for piece in current.iter_text():
                    if piece:
                        print(piece, end="", flush=True)
                        streamed = True
                        chunks.append(piece)
                    barge = _barge_in_during(listener, wake_word=wake_word)
                    if barge is not MISSING:
                        break
                if streamed:
                    print(flush=True)
            except Exception as exc:
                print(f"voice-cursor: agent error ({exc})", file=sys.stderr)
                if current is not None:
                    current.cancel()
                speaker.stop()
                session.end_turn()
                current = None
                _speak(speaker, "The agent hit an error. Try again.", session=session)
                heard = listener.next_utterance()
                continue
            if barge is MISSING:
                barge = _barge_in_during(listener, wake_word=wake_word)
            if barge is not MISSING:
                nxt = _barge(
                    barge,
                    current=current,
                    speaker=speaker,
                    session=session,
                    wake_word=wake_word,
                )
                current = None
                if nxt is _STOP:
                    break
                if nxt is _LISTEN:
                    heard = listener.next_utterance()
                    continue
                heard = nxt
                continue
            try:
                result = current.wait()
            except Exception as exc:
                print(f"voice-cursor: agent error ({exc})", file=sys.stderr)
                speaker.stop()
                session.end_turn()
                current = None
                _speak(speaker, "The agent hit an error. Try again.", session=session)
                heard = listener.next_utterance()
                continue
            if getattr(current, "status", "") == "error":
                _speak(speaker, "The agent hit an error. Try again.", session=session)
                session.end_turn()
                current = None
                heard = listener.next_utterance()
                continue
            final = "".join(chunks) or result
            session.begin_speak()
            spoken = speakable(final)
            if spoken:
                _speak(speaker, spoken, echo=not streamed, session=session)
            speak_barge = MISSING
            key_poll = getattr(interrupt_key, "poll", None)
            interrupted_for_listen = False
            while _playing(speaker):
                if key_poll is not None and key_poll():
                    speaker.stop()
                    session.end_turn()
                    current = None
                    interrupted_for_listen = True
                    break
                speak_barge = _barge_in_during(
                    listener, wake_word=wake_word, speaking=True
                )
                if speak_barge is not MISSING:
                    break
                time.sleep(0.05)
            if interrupted_for_listen:
                heard = listener.next_utterance()
                continue
            if speak_barge is not MISSING:
                nxt = _barge(
                    speak_barge,
                    current=current,
                    speaker=speaker,
                    session=session,
                    wake_word=wake_word,
                    speaking=True,
                )
                current = None
                if nxt is _STOP:
                    break
                if nxt is _LISTEN:
                    heard = listener.next_utterance()
                    continue
                heard = nxt
                continue
            session.end_turn()
            current = None
            heard = listener.next_utterance()
    finally:
        speaker.stop()
        closer = getattr(listener, "close", None)
        if closer is not None:
            closer()
        key_close = getattr(interrupt_key, "close", None)
        if key_close is not None:
            key_close()
        agent.close()
        talk.close()
