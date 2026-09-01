from __future__ import annotations

from difflib import SequenceMatcher
from enum import Enum


class Intent(Enum):
    STOP_SESSION = "stop_session"
    CANCEL_RUN = "cancel_run"
    QUIET = "quiet"
    PROMPT = "prompt"
    APPLY = "apply"
    IGNORE = "ignore"


_STOP = frozenset(
    {
        "stop listening",
        "goodbye",
        "goodbye cursor",
        "exit",
        "quit",
        "stop session",
        "end session",
    }
)
_CANCEL = frozenset({"cancel", "never mind", "nevermind"})
_QUIET = frozenset({"be quiet", "silence", "shut up", "quiet"})
# Longest first so "apply that" is not parsed as apply + "that".
_APPLY = (
    "make the change",
    "implement it",
    "apply that",
    "go ahead",
    "do it",
    "apply",
)
_APPLY_ALIASES = frozenset({"applied", "applying", "apply please"})
_APPLY_DENY = frozenset({"reply", "supply", "simply", "apple", "happy"})
_FUZZY = 0.82


def normalize(text: str) -> str:
    chars = []
    for c in text.lower().strip():
        chars.append(c if c.isalnum() or c.isspace() else " ")
    return " ".join("".join(chars).split())


def _close(a: str, b: str, cutoff: float = _FUZZY) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= cutoff


def _matches(key: str, phrases: frozenset[str] | tuple[str, ...]) -> bool:
    if key in phrases:
        return True
    return any(_close(key, p) for p in phrases)


def strip_wake_word(text: str, wake: str) -> str | None:
    """Return text after a position-0 wake prefix, or None if the prefix is absent."""
    wake = normalize(wake)
    if not wake:
        return text
    tokens = text.split()
    wake_tokens = wake.split()
    n = len(wake_tokens)
    if len(tokens) < n:
        return None
    head = [t.strip(".,!?:;").lower() for t in tokens[:n]]
    if head != wake_tokens:
        return None
    return " ".join(tokens[n:]).strip(" ,.!?:;")


def classify(
    text: str, *, run_active: bool = False, wake_word: str = ""
) -> tuple[Intent, str]:
    payload = text.strip()
    if wake_word:
        stripped = strip_wake_word(payload, wake_word)
        if stripped is None:
            return Intent.IGNORE, payload
        payload = stripped
    key = normalize(payload)
    if not key:
        return Intent.IGNORE, payload
    if _matches(key, _STOP):
        return Intent.STOP_SESSION, payload
    if _matches(key, _QUIET):
        return Intent.QUIET, payload
    if key == "stop" or _close(key, "stop"):
        if run_active:
            return Intent.CANCEL_RUN, payload
        return Intent.STOP_SESSION, payload
    if run_active and _matches(key, _CANCEL):
        return Intent.CANCEL_RUN, payload
    for phrase in _APPLY:
        if key == phrase or _close(key, phrase):
            return Intent.APPLY, ""
        prefix = phrase + " "
        if key.startswith(prefix):
            return Intent.APPLY, key[len(prefix) :]
    tokens = key.split()
    head = tokens[0] if tokens else ""
    if head not in _APPLY_DENY and (
        head in _APPLY_ALIASES or _close(head, "apply")
    ):
        return Intent.APPLY, " ".join(tokens[1:])
    return Intent.PROMPT, payload
