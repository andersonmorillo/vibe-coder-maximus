from pathlib import Path

from voice_cursor.fake import FakeAgent
from voice_cursor.io import ListListener, RecordingSpeaker
from voice_cursor.loop import run_session
from voice_cursor.spec import read_spec, write_spec


def _run(*, listener, speaker, agent, talk, spec_root, wake_word=""):
    run_session(
        listener=listener,
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=spec_root,
        wake_word=wake_word,
    )


def test_fake_talk_then_apply(tmp_path: Path):
    from voice_cursor.fake import FakeTalkAgent

    talk = FakeTalkAgent(spec_root=str(tmp_path), replies=["Saved. Say apply."])
    agent = FakeAgent(replies=["Done."])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["create a login endpoint", "apply", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["create a login endpoint"]
    assert read_spec(tmp_path) == "create a login endpoint"
    assert len(agent.prompts) == 1
    assert speaker.said == ["Saved. Say apply.", "Applying. create a login endpoint", "Done."]
    assert talk.closed and agent.closed


def test_talk_does_not_call_coding_agent(tmp_path: Path):
    talk = FakeAgent(replies=["Noted. Say apply when you want Cursor to edit."])
    agent = FakeAgent(replies=["should not run"])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["create a login endpoint", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["create a login endpoint"]
    assert agent.prompts == []
    assert speaker.said == ["Noted. Say apply when you want Cursor to edit."]
    assert talk.closed and agent.closed


def test_apply_runs_coding_agent_once(tmp_path: Path):
    write_spec(tmp_path, "add a login endpoint")
    talk = FakeAgent(replies=["unused"])
    agent = FakeAgent(replies=["Created the login endpoint."])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["apply", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == []
    assert len(agent.prompts) == 1
    assert ".voice-cursor/request.md" in agent.prompts[0]
    assert speaker.said == ["Applying. add a login endpoint", "Created the login endpoint."]


def test_empty_apply_does_not_call_coding_agent(tmp_path: Path):
    talk = FakeAgent()
    agent = FakeAgent(replies=["should not run"])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["apply", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert agent.prompts == []
    assert talk.prompts == []
    assert speaker.said == ["Nothing to apply."]


def test_apply_with_words_writes_spec(tmp_path: Path):
    talk = FakeAgent()
    agent = FakeAgent(replies=["Renamed it."])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["apply rename foo to bar", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert read_spec(tmp_path) == "rename foo to bar"
    assert len(agent.prompts) == 1
    assert speaker.said == ["Applying. rename foo to bar", "Renamed it."]


def test_firstmate_engine_queues_spec_text(tmp_path: Path):
    class FirstmateFake(FakeAgent):
        apply_message = "Handing to Firstmate."
        uses_request_text = True

    talk = FakeAgent()
    agent = FirstmateFake(replies=["Queued for Firstmate."])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["apply rename foo to bar", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert agent.prompts == ["rename foo to bar"]
    assert speaker.said == ["Handing to Firstmate. rename foo to bar", "Queued for Firstmate."]


def test_agent_send_error_keeps_listening(tmp_path: Path):
    class Boom:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.closed = False

        def send(self, prompt: str):
            self.prompts.append(prompt)
            raise RuntimeError("boom")

        def close(self) -> None:
            self.closed = True

    talk = Boom()
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["do the thing", "quit"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["do the thing"]
    assert agent.prompts == []
    assert speaker.said == ["The agent hit an error. Try again."]
    assert talk.closed


def test_run_status_error_is_spoken_not_partial(tmp_path: Path):
    write_spec(tmp_path, "do a thing")

    class ErrRun:
        status = "error"

        def iter_text(self):
            yield "partial junk"

        def wait(self) -> str:
            return ""

        def cancel(self) -> None:
            pass

    class ErrAgent:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.closed = False

        def send(self, prompt: str):
            self.prompts.append(prompt)
            return ErrRun()

        def close(self) -> None:
            self.closed = True

    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["do it", "quit"]),
        speaker=speaker,
        agent=ErrAgent(),
        talk=FakeAgent(),
        spec_root=tmp_path,
    )
    assert speaker.said == [
        "Applying. do a thing",
        "The agent hit an error. Try again.",
    ]


def test_two_talk_turns_then_stop(tmp_path: Path):
    talk = FakeAgent(replies=["Let's plan the login.", "JWT next."])
    agent = FakeAgent(replies=["should not run"])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(
            [
                "create a login endpoint",
                "now add JWT authentication",
                "stop listening",
            ]
        ),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == [
        "create a login endpoint",
        "now add JWT authentication",
    ]
    assert agent.prompts == []
    assert speaker.said == ["Let's plan the login.", "JWT next."]


def test_stop_does_not_send_to_agent(tmp_path: Path):
    talk = FakeAgent()
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["stop listening"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == []
    assert agent.prompts == []
    assert speaker.said == []


class _PollListener:
    """Lines for next_utterance; one-shot poll() barges in during a run."""

    def __init__(self, lines: list[str], polls: list[str]) -> None:
        self._lines = list(lines)
        self._polls = list(polls)

    def next_utterance(self) -> str | None:
        if not self._lines:
            return None
        return self._lines.pop(0)

    def poll(self):
        from voice_cursor.ports import MISSING

        if not self._polls:
            return MISSING
        return self._polls.pop(0)


def test_poll_cancel_does_not_speak_and_does_not_follow_up(tmp_path: Path):
    talk = FakeAgent(replies=["should not be spoken"])
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=_PollListener(lines=["first task", "quit"], polls=["cancel"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task"]
    assert agent.prompts == []
    assert speaker.said == []


def test_poll_new_prompt_replaces_in_flight_run(tmp_path: Path):
    talk = FakeAgent(replies=["first", "second"])
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=_PollListener(lines=["first task"], polls=["now add JWT"]),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task", "now add JWT"]
    assert agent.prompts == []
    assert speaker.said == ["second"]


def test_wake_word_filters_noise(tmp_path: Path):
    talk = FakeAgent(replies=["ok"])
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(
            ["side conversation", "hey cursor make a file", "goodbye"]
        ),
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
        wake_word="hey cursor",
    )
    assert talk.prompts == ["make a file"]
    assert agent.prompts == []


class _StickySpeaker:
    def __init__(self, arm) -> None:
        self.said: list[str] = []
        self.stops = 0
        self._playing = False
        self._arm = arm

    def say(self, text: str) -> None:
        self.said.append(text)
        self._playing = True
        self._arm()

    def is_playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        self.stops += 1
        self._playing = False


def test_barge_in_during_speech_cancels_without_waiting(tmp_path: Path):
    listener = _PollListener(lines=["first task"], polls=[])
    speaker = _StickySpeaker(arm=lambda: listener._polls.append("cancel"))
    talk = FakeAgent(replies=["long spoken answer"])
    agent = FakeAgent()
    _run(
        listener=listener,
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task"]
    assert agent.prompts == []
    assert speaker.said == ["long spoken answer"]
    assert speaker.stops >= 1


class _BriefSpeaker:
    """Simulates short TTS: playing for a few poll ticks, then finishes."""

    def __init__(self, on_say) -> None:
        self.said: list[str] = []
        self.stops = 0
        self._playing = False
        self._ticks = 0
        self._on_say = on_say

    def say(self, text: str) -> None:
        self.said.append(text)
        self._playing = True
        self._ticks = 2
        self._on_say()

    def is_playing(self) -> bool:
        if not self._playing:
            return False
        if self._ticks <= 0:
            self._playing = False
            return False
        self._ticks -= 1
        return True

    def stop(self) -> None:
        self.stops += 1
        self._playing = False


def test_prompt_during_speech_does_not_interrupt(tmp_path: Path):
    listener = _PollListener(lines=["first task", "quit"], polls=[])
    speaker = _BriefSpeaker(on_say=lambda: listener._polls.append("now add JWT"))
    talk = FakeAgent(replies=["long spoken answer"])
    agent = FakeAgent()
    _run(
        listener=listener,
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task"]
    assert agent.prompts == []
    assert speaker.said == ["long spoken answer"]
    assert "JWT" not in " ".join(talk.prompts)


def test_stop_during_speech_waits_for_next_sentence(tmp_path: Path):
    listener = _PollListener(
        lines=["first task", "add JWT auth", "quit"],
        polls=[],
    )
    speaker = _StickySpeaker(arm=lambda: listener._polls.append("stop"))
    talk = FakeAgent(replies=["long spoken answer", "noted JWT"])
    agent = FakeAgent()
    _run(
        listener=listener,
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task", "add JWT auth"]
    assert speaker.stops >= 1


class _KeyInterrupt:
    def __init__(self) -> None:
        self._armed = False
        self.closed = False

    def arm(self) -> None:
        self._armed = True

    def poll(self) -> bool:
        if self._armed:
            self._armed = False
            return True
        return False

    def close(self) -> None:
        self.closed = True


def test_enter_during_speech_waits_for_next_sentence(tmp_path: Path):
    listener = _PollListener(lines=["first task", "add JWT auth", "quit"], polls=[])
    key = _KeyInterrupt()
    speaker = _StickySpeaker(arm=key.arm)
    talk = FakeAgent(replies=["long spoken answer", "noted JWT"])
    agent = FakeAgent()
    run_session(
        listener=listener,
        speaker=speaker,
        agent=agent,
        talk=talk,
        spec_root=tmp_path,
        interrupt_key=key,
    )
    assert talk.prompts == ["first task", "add JWT auth"]
    assert speaker.stops >= 1
    assert key.closed


def test_help_does_not_call_talk(tmp_path: Path):
    from voice_cursor.commands import HELP_SPEECH

    talk = FakeAgent(replies=["should not run"])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["help", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == []
    assert speaker.said == [HELP_SPEECH]


def test_status_reads_pending_spec(tmp_path: Path):
    write_spec(tmp_path, "add a login endpoint")
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["status", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=FakeAgent(),
        spec_root=tmp_path,
    )
    assert speaker.said == ["Pending change: add a login endpoint"]


def test_status_without_spec(tmp_path: Path):
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["what's the plan", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=FakeAgent(),
        spec_root=tmp_path,
    )
    assert speaker.said == ["No pending change. Talk to plan one, then say apply."]


def test_repeat_respeaks_last_reply(tmp_path: Path):
    talk = FakeAgent(replies=["Saved. Say apply."])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["create a login endpoint", "repeat", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["create a login endpoint"]
    assert speaker.said == ["Saved. Say apply.", "Saved. Say apply."]


def test_forget_that_clears_spec(tmp_path: Path):
    write_spec(tmp_path, "add a login endpoint")
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["forget that", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=FakeAgent(),
        spec_root=tmp_path,
    )
    assert read_spec(tmp_path) == ""
    assert speaker.said == ["Dropped the pending change."]


def test_yeah_is_not_a_talk_turn(tmp_path: Path):
    talk = FakeAgent(replies=["should not run"])
    speaker = RecordingSpeaker()
    _run(
        listener=ListListener(["yeah", "quit"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == []
    assert speaker.said == []


class _TwoShotRun:
    def __init__(self) -> None:
        self.cancelled = False

    def iter_text(self):
        yield "part one "
        yield "part two"

    def wait(self) -> str:
        return "part one part two"

    def cancel(self) -> None:
        self.cancelled = True


class _TwoShotAgent:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.closed = False
        self.run: _TwoShotRun | None = None

    def send(self, prompt: str) -> _TwoShotRun:
        self.prompts.append(prompt)
        self.run = _TwoShotRun()
        return self.run

    def close(self) -> None:
        self.closed = True


def test_backchannel_during_run_does_not_abort(tmp_path: Path):
    talk = _TwoShotAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=_PollListener(lines=["first task", "quit"], polls=["yeah"]),
        speaker=speaker,
        agent=FakeAgent(),
        talk=talk,
        spec_root=tmp_path,
    )
    assert talk.prompts == ["first task"]
    assert talk.run is not None and not talk.run.cancelled
    assert speaker.said == ["part one part two"]


def test_wake_miss_during_run_does_not_abort(tmp_path: Path):
    talk = _TwoShotAgent()
    speaker = RecordingSpeaker()
    _run(
        listener=_PollListener(
            lines=["hey cursor first task", "hey cursor quit"],
            polls=["side conversation"],
        ),
        speaker=speaker,
        agent=FakeAgent(),
        talk=talk,
        spec_root=tmp_path,
        wake_word="hey cursor",
    )
    assert talk.prompts == ["first task"]
    assert talk.run is not None and not talk.run.cancelled
    assert speaker.said == ["part one part two"]
