from __future__ import annotations

import os
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"


def is_placeholder_key(value: str) -> bool:
    v = value.strip().lower()
    if not v:
        return True
    return any(
        n in v
        for n in ("your-key", "your_key", "changeme", "placeholder", "example")
    )


def load_dotenv(path: str | Path, *, override: bool = False) -> None:
    """Load KEY=VALUE from a .env file. Never logs values."""
    file = Path(path)
    if not file.is_file():
        return
    try:
        raw = file.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and (override or key not in os.environ):
            os.environ[key] = value


def voice_cursor_home() -> Path:
    override = os.environ.get("VOICE_CURSOR_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".voice-cursor"


def load_cwd_dotenv(cwd: str | Path) -> None:
    load_talk_env(cwd)


def load_talk_env(cwd: str | Path) -> None:
    """Talk keys from files, not a stale shell env.

    Global ~/.voice-cursor/.env first, then --cwd/.env (wins). Both override
    inherited OPENROUTER_API_KEY so `voice-cursor start` matches the repo .env.
    """
    load_dotenv(voice_cursor_home() / ".env", override=True)
    load_dotenv(Path(cwd) / ".env", override=True)


def talk_llm() -> dict[str, str]:
    """Resolved talk provider. Empty provider means no key."""
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if is_placeholder_key(or_key):
        or_key = ""
    oai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if is_placeholder_key(oai_key):
        oai_key = ""
    anth = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "").strip()
    model = (
        os.environ.get("OPENAI_DEFAULT_MODEL", "").strip()
        or os.environ.get("OPENROUTER_MODEL", "").strip()
    )
    if or_key:
        return {
            "provider": "openai",
            "api_key": or_key,
            "base_url": base or OPENROUTER_BASE,
            "model": model or OPENROUTER_DEFAULT_MODEL,
        }
    if oai_key and "openrouter.ai" in base:
        return {
            "provider": "openai",
            "api_key": oai_key,
            "base_url": base,
            "model": model or OPENROUTER_DEFAULT_MODEL,
        }
    if oai_key:
        out = {"provider": "openai", "api_key": oai_key, "base_url": base, "model": model}
        return out
    if anth:
        return {"provider": "anthropic", "api_key": anth, "base_url": "", "model": ""}
    return {"provider": "", "api_key": "", "base_url": "", "model": ""}


def apply_talk_credentials() -> dict[str, str]:
    """Point the OpenAI client at the resolved talk provider. Overwrites OPENAI_*."""
    spec = talk_llm()
    if spec["provider"] == "openai" and spec["api_key"]:
        os.environ["OPENAI_API_KEY"] = spec["api_key"]
        if spec["base_url"]:
            os.environ["OPENAI_BASE_URL"] = spec["base_url"]
        if spec["model"]:
            os.environ["OPENAI_DEFAULT_MODEL"] = spec["model"]
    return spec
