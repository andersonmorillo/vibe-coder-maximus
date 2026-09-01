from __future__ import annotations

from voice_cursor.ports import CodingAgent, Run


class FakeRun:
    def __init__(self, text: str) -> None:
        self._text = text
        self.cancelled = False

    def iter_text(self):
        if not self.cancelled and self._text:
            yield self._text

    def wait(self) -> str:
        return "" if self.cancelled else self._text

    def cancel(self) -> None:
        self.cancelled = True


class FakeAgent:
    """In-process agent for tests and `voice-cursor start --fake`."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self.replies = list(replies or ["Done."])
        self.closed = False

    def send(self, prompt: str) -> Run:
        self.prompts.append(prompt)
        idx = min(len(self.prompts) - 1, len(self.replies) - 1)
        return FakeRun(self.replies[idx])

    def close(self) -> None:
        self.closed = True
