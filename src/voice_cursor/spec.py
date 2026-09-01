from __future__ import annotations

from pathlib import Path

_REL = Path(".voice-cursor") / "request.md"


def spec_file(root: str | Path) -> Path:
    base = Path(root).expanduser().resolve()
    path = (base / _REL).resolve()
    path.relative_to(base)
    return path


def read_spec(root: str | Path) -> str:
    path = spec_file(root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_spec(root: str | Path, text: str) -> Path:
    path = spec_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path
