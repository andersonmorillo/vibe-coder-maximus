from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from voice_cursor.cursor_cli import cli_authenticated, find_agent_cli
from voice_cursor.envfile import (
    apply_talk_credentials,
    key_suffix,
    load_talk_env,
    talk_llm,
    talk_status_line,
)
from voice_cursor.firstmate import (
    primary_session_name,
    resolve_firstmate_home,
    resolve_firstmate_root,
)
from voice_cursor.stt import cuda_device_count, resolve_stt_device, runtime_summary, stt_model_name
from voice_cursor.win_mic import mic_backend


def _ping_openrouter(api_key: str, base: str) -> str:
    url = (base or "https://openrouter.ai/api/v1").rstrip("/") + "/models"
    req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        n = len(data.get("data") or [])
        return f"ok ({n} models)"
    except HTTPError as exc:
        return f"http {exc.code}"
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return f"fail ({exc.__class__.__name__})"


def doctor_lines(cwd: str | Path) -> list[str]:
    cwd = Path(cwd).expanduser().resolve()
    load_talk_env(cwd)
    apply_talk_credentials()
    spec = talk_llm()
    cuda_n = cuda_device_count()
    device, compute = resolve_stt_device(cuda_n)
    binary = find_agent_cli()
    lines = [
        f"cwd: {cwd}",
        f"cuda devices: {cuda_n}",
        f"stt: {stt_model_name()} on {device} ({compute})",
        f"stt runtime: {runtime_summary()}",
        talk_status_line(),
    ]
    if spec["api_key"]:
        lines.append(f"talk key suffix: ...{key_suffix(spec['api_key'])}")
        if "openrouter.ai" in (spec["base_url"] or ""):
            lines.append(
                "openrouter: " + _ping_openrouter(spec["api_key"], spec["base_url"])
            )
    else:
        lines.append("talk key: missing")
    if binary:
        logged = cli_authenticated(binary)
        lines.append(f"agent cli: {binary}")
        lines.append("agent login: " + ("ok" if logged else "not logged in"))
    else:
        lines.append("agent cli: missing")
    try:
        firstmate_root = resolve_firstmate_root(cwd=cwd)
    except RuntimeError as exc:
        lines.append(f"firstmate: unavailable ({exc})")
    else:
        firstmate_home = resolve_firstmate_home(firstmate_root)
        session = primary_session_name(firstmate_root, firstmate_home)
        lines.append(f"firstmate root: {firstmate_root}")
        lines.append(f"firstmate home: {firstmate_home}")
        lines.append(
            "firstmate tmux: " + ("ok" if shutil.which("tmux") else "missing")
        )
        lines.append(f"firstmate session: {session}")
    mic = os.environ.get("VOICE_CURSOR_MIC_DEVICE", "").strip() or "default"
    lines.append(f"mic capture: {mic_backend()}")
    lines.append(f"mic device: {mic}")
    try:
        from voice_cursor.stt import describe_input_devices

        lines.append("input devices:")
        lines.append(describe_input_devices())
    except Exception as exc:
        lines.append(f"input devices: unavailable ({exc})")
    return lines


def talk_ok() -> bool:
    return bool(talk_llm()["api_key"])


def run_doctor(cwd: str | Path = ".") -> int:
    lines = doctor_lines(cwd)
    for line in lines:
        print(line)
    return 0 if talk_ok() else 1
