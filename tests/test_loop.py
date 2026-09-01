from voice_cursor.fake import FakeAgent
from voice_cursor.io import ListListener, RecordingSpeaker
from voice_cursor.loop import run_session


def test_agent_send_error_keeps_listening():
    class Boom:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.closed = False

        def send(self, prompt: str):
            self.prompts.append(prompt)
            raise RuntimeError("boom")

        def close(self) -> None:
            self.closed = True

    agent = Boom()
    speaker = RecordingSpeaker()
    run_session(
        listener=ListListener(["do the thing", "quit"]),
        speaker=speaker,
        agent=agent,
    )
    assert agent.prompts == ["do the thing"]
    assert speaker.said == ["The agent hit an error. Try again."]
    assert agent.closed


def test_run_status_error_is_spoken_not_partial():
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
            self.closed = False

        def send(self, prompt: str):
            return ErrRun()

        def close(self) -> None:
            self.closed = True

    speaker = RecordingSpeaker()
    run_session(
        listener=ListListener(["do it", "quit"]),
        speaker=speaker,
        agent=ErrAgent(),
    )
    assert speaker.said == ["The agent hit an error. Try again."]


def test_two_turns_then_stop():
    agent = FakeAgent(replies=["Created the login endpoint.", "Added JWT."])
    speaker = RecordingSpeaker()
    listener = ListListener(
        [
            "create a login endpoint",
            "now add JWT authentication",
            "stop listening",
        ]
    )
    run_session(listener=listener, speaker=speaker, agent=agent)
    assert agent.prompts == [
        "create a login endpoint",
        "now add JWT authentication",
    ]
    assert speaker.said == ["Created the login endpoint.", "Added JWT."]
    assert agent.closed


def test_stop_does_not_send_to_agent():
    agent = FakeAgent()
    speaker = RecordingSpeaker()
    run_session(
        listener=ListListener(["stop listening"]),
        speaker=speaker,
        agent=agent,
    )
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


def test_poll_cancel_does_not_speak_and_does_not_follow_up():
    agent = FakeAgent(replies=["should not be spoken"])
    speaker = RecordingSpeaker()
    run_session(
        listener=_PollListener(lines=["first task", "quit"], polls=["cancel"]),
        speaker=speaker,
        agent=agent,
    )
    assert agent.prompts == ["first task"]
    assert speaker.said == []


def test_poll_new_prompt_replaces_in_flight_run():
    agent = FakeAgent(replies=["first", "second"])
    speaker = RecordingSpeaker()
    run_session(
        listener=_PollListener(lines=["first task"], polls=["now add JWT"]),
        speaker=speaker,
        agent=agent,
    )
    assert agent.prompts == ["first task", "now add JWT"]
    assert speaker.said == ["second"]


def test_wake_word_filters_noise():
    agent = FakeAgent(replies=["ok"])
    speaker = RecordingSpeaker()
    run_session(
        listener=ListListener(
            ["side conversation", "hey cursor make a file", "goodbye"]
        ),
        speaker=speaker,
        agent=agent,
        wake_word="hey cursor",
    )
    assert agent.prompts == ["make a file"]


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


def test_barge_in_during_speech_cancels_without_waiting():
    listener = _PollListener(lines=["first task"], polls=[])
    speaker = _StickySpeaker(arm=lambda: listener._polls.append("cancel"))
    agent = FakeAgent(replies=["long spoken answer"])
    run_session(listener=listener, speaker=speaker, agent=agent)
    assert agent.prompts == ["first task"]
    assert speaker.said == ["long spoken answer"]
    assert speaker.stops >= 1
