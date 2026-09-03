from __future__ import annotations

from difflib import SequenceMatcher
from enum import Enum


class Intent(Enum):
    STOP_SESSION = "stop_session"
    CANCEL_RUN = "cancel_run"
    QUIET = "quiet"
    HELP = "help"
    STATUS = "status"
    REPEAT = "repeat"
    CLEAR = "clear"
    BACKCHANNEL = "backchannel"
    PROMPT = "prompt"
    APPLY = "apply"
    IGNORE = "ignore"


GREETING_SPEECH = (
    "Listening. Talk to plan a change, say apply to hand it off, "
    "or say help for commands."
)
HELP_SPEECH = (
    "Talk to plan. Say apply to hand it to Firstmate. "
    "Say status to hear the pending plan, repeat to hear me again, "
    "forget that to drop the plan, or stop listening to end."
)

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
_HELP = frozenset(
    {
        "help",
        "what can i say",
        "what can you do",
        "commands",
        "help commands",
    }
)
_STATUS = frozenset(
    {
        "status",
        "what s the plan",
        "whats the plan",
        "what is the plan",
        "where are we",
        "read the spec",
        "what s the spec",
        "whats the spec",
        "what is the spec",
    }
)
_REPEAT = frozenset(
    {
        "repeat",
        "repeat that",
        "say that again",
        "say it again",
        "what did you say",
    }
)
_CLEAR = frozenset(
    {
        "forget that",
        "clear the plan",
        "scratch that",
        "drop the spec",
        "drop the plan",
    }
)
# Exact only: short ack words must not steal real prompts via fuzzy match.
_BACKCHANNEL = frozenset(
    {
        "yeah",
        "yes",
        "yep",
        "yup",
        "ok",
        "okay",
        "uh huh",
        "uhhuh",
        "right",
        "mm hmm",
        "mhm",
        "got it",
        "cool",
        "sure",
        "alright",
        "all right",
    }
)
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


def is_background(intent: Intent) -> bool:
    return intent in (Intent.IGNORE, Intent.BACKCHANNEL)


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
    if _matches(key, _HELP):
        return Intent.HELP, payload
    if _matches(key, _STATUS):
        return Intent.STATUS, payload
    if _matches(key, _REPEAT):
        return Intent.REPEAT, payload
    if _matches(key, _CLEAR):
        if run_active:
            return Intent.CANCEL_RUN, payload
        return Intent.CLEAR, payload
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
    if key in _BACKCHANNEL:
        return Intent.BACKCHANNEL, payload
    return Intent.PROMPT, payload
