from __future__ import annotations

import re

_FENCE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_LIST = re.compile(r"^\s{0,3}(?:[-*+]|\d+\.)\s+", re.M)
_EMPH = re.compile(r"[*_~]{1,3}")


def _keep_inline(match: re.Match[str]) -> str:
    inner = match.group(1)
    if len(inner) > 24 and " " not in inner:
        return " "
    if re.match(r"^[A-Za-z]:[\\/]", inner):
        return " "
    return inner


def spoken_preview(text: str, limit: int = 240) -> str:
    """One flattened line for status / receipts; empty input stays empty."""
    one = " ".join(text.split())
    if len(one) <= limit:
        return one
    return one[: limit - 3].rstrip() + "..."


def speakable(text: str) -> str:
    """Strip markdown and code so TTS does not read fences aloud."""
    if not text:
        return ""
    s = _FENCE.sub(" ", text)
    s = _INLINE_CODE.sub(_keep_inline, s)
    s = _HEADING.sub("", s)
    s = _LIST.sub("", s)
    s = _EMPH.sub("", s)
    s = s.replace("**", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s
