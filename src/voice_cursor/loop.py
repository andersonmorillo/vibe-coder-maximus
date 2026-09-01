from __future__ import annotations

import sys
import time
from pathlib import Path

from voice_cursor.commands import Intent, classify
from voice_cursor.ports import MISSING, CodingAgent, Listener, Speaker
from voice_cursor.session import Session
from voice_cursor.speakable import speakable
from voice_cursor.spec import read_spec, write_spec

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


def _reap(run) -> None:
    if run is None:
        return
    try:
        run.wait()
    except Exception:
        pass


def _barge(barge, *, current, speaker: Speaker, session: Session, wake_word: str):
    intent_b, _ = classify(barge, run_active=True, wake_word=wake_word)
    if current is not None:
        current.cancel()
        _reap(current)
    speaker.stop()
    session.end_turn()
    if intent_b is Intent.STOP_SESSION:
        session.stop()
        return _STOP
    if intent_b in (Intent.CANCEL_RUN, Intent.QUIET, Intent.IGNORE):
        return _LISTEN
    return barge


def run_session(
    *,
    listener: Listener,
    speaker: Speaker,
    agent: CodingAgent,
    talk: CodingAgent,
    spec_root: str | Path = ".",
    wake_word: str = "",
) -> None:
    session = Session()
    current = None
    heard = listener.next_utterance()
    try:
        while session.is_open:
            if heard is None:
                session.stop()
                break
            intent, payload = classify(
                heard, run_active=session.run_active, wake_word=wake_word
            )
            if intent is Intent.IGNORE:
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
            if current is not None and session.run_active:
                current.cancel()
                _reap(current)
                speaker.stop()
            if intent is Intent.APPLY:
                if payload:
                    write_spec(spec_root, payload)
                if not read_spec(spec_root):
                    speaker.say("Nothing to apply.")
                    heard = listener.next_utterance()
                    continue
                prompt = APPLY_PROMPT
                worker: CodingAgent = agent
                label = "cursor"
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
                for piece in current.iter_text():
                    chunks.append(piece)
                    barge = _poll(listener)
                    if barge is not MISSING:
                        break
            except Exception as exc:
                print(f"voice-cursor: agent error ({exc})", file=sys.stderr)
                if current is not None:
                    current.cancel()
                speaker.stop()
                session.end_turn()
                current = None
                speaker.say("The agent hit an error. Try again.")
                heard = listener.next_utterance()
                continue
            if barge is MISSING:
                barge = _poll(listener)
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
                speaker.say("The agent hit an error. Try again.")
                heard = listener.next_utterance()
                continue
            if getattr(current, "status", "") == "error":
                speaker.say("The agent hit an error. Try again.")
                session.end_turn()
                current = None
                heard = listener.next_utterance()
                continue
            final = "".join(chunks) or result
            session.begin_speak()
            spoken = speakable(final)
            if spoken:
                speaker.say(spoken)
            speak_barge = MISSING
            while _playing(speaker):
                speak_barge = _poll(listener)
                if speak_barge is not MISSING:
                    break
                time.sleep(0.05)
            if speak_barge is not MISSING:
                nxt = _barge(
                    speak_barge,
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
            session.end_turn()
            current = None
            heard = listener.next_utterance()
    finally:
        speaker.stop()
        closer = getattr(listener, "close", None)
        if closer is not None:
            closer()
        agent.close()
        talk.close()
