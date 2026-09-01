from __future__ import annotations


class ListListener:
    """Replay canned utterances, then EOF. poll() is always empty (sequential)."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def next_utterance(self) -> str | None:
        if not self._lines:
            return None
        return self._lines.pop(0)


class StdinListener:
    """Typed fallback. Sequential; barge-in is the mic listener's job."""

    def next_utterance(self) -> str | None:
        try:
            return input("you> ")
        except EOFError:
            return None


class RecordingSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.stops = 0

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1


class PrintSpeaker:
    def say(self, text: str) -> None:
        print(f"cursor> {text}")

    def stop(self) -> None:
        pass


class TeeSpeaker:
    """Always print. Optionally speak without blocking the print path."""

    def __init__(self, voice: object | None = None) -> None:
        self._print = PrintSpeaker()
        self._voice = voice

    def say(self, text: str) -> None:
        self._print.say(text)
        if self._voice is not None:
            self._voice.say(text)

    def is_playing(self) -> bool:
        playing = getattr(self._voice, "is_playing", None)
        return bool(playing()) if playing else False

    def stop(self) -> None:
        if self._voice is not None:
            self._voice.stop()
