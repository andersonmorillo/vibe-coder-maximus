from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_KEY_FILE = Path.home() / ".cursor" / "api-key"


def prompt_api_key() -> str:
    """Hidden TTY prompt. Never echo. No-op when stdin is not a terminal."""
    if not sys.stdin.isatty():
        return ""
    import getpass

    try:
        return getpass.getpass("CURSOR_API_KEY (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def load_api_key(file_path: str | None = None) -> str:
    """Author-typed key only. Never log the value."""
    env = os.environ.get("CURSOR_API_KEY", "").strip()
    if env:
        return env
    paths = []
    if file_path:
        paths.append(Path(file_path).expanduser())
    extra = os.environ.get("VOICE_CURSOR_API_KEY_FILE", "").strip()
    if extra:
        paths.append(Path(extra).expanduser())
    paths.append(DEFAULT_KEY_FILE)
    for path in paths:
        try:
            if path.is_file():
                line = path.read_text(encoding="utf-8").strip().splitlines()
                if line:
                    return line[0].strip()
        except OSError:
            continue
    return ""
