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


class FakeTalkAgent(FakeAgent):
    """Talk fake that writes the utterance into the apply spec (so --fake apply works)."""

    def __init__(
        self, spec_root: str, replies: list[str] | None = None
    ) -> None:
        super().__init__(replies=replies or ["Noted. Say apply when you want Cursor to edit."])
        self._spec_root = spec_root

    def send(self, prompt: str) -> Run:
        from voice_cursor.spec import write_spec

        write_spec(self._spec_root, prompt)
        return super().send(prompt)
