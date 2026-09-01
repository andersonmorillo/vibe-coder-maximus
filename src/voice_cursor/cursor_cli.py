from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

from voice_cursor.keys import load_api_key
from voice_cursor.loop import VOICE_INSTRUCTION


def find_agent_cli() -> str | None:
    """Cursor CLI (`agent`), not the Python SDK and not Windows-MCP."""
    override = os.environ.get("VOICE_CURSOR_AGENT_BIN", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
    which = shutil.which("agent")
    if which:
        return which
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        home / ".local" / "bin" / "agent.exe",
        home / ".local" / "bin" / "agent.cmd",
        home / ".local" / "bin" / "agent",
        home / ".cursor" / "bin" / "agent.exe",
        home / ".cursor" / "bin" / "agent.cmd",
        Path(local) / "cursor-agent" / "agent.exe" if local else None,
        Path(local) / "cursor-agent" / "agent.cmd" if local else None,
        Path(local) / "cursor-agent" / "agent.ps1" if local else None,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return str(path)
    return None


def _launch_argv(binary: str) -> list[str]:
    path = Path(binary)
    if path.suffix.lower() == ".ps1":
        return ["powershell", "-NoProfile", "-File", str(path)]
    return [str(path)]


def install_hint() -> str:
    if sys.platform == "win32":
        return (
            "voice-cursor: Cursor CLI (`agent`) not found. Install with: "
            "irm 'https://cursor.com/install?win32=true' | iex"
        )
    return (
        "voice-cursor: Cursor CLI (`agent`) not found. Install with: "
        "curl https://cursor.com/install -fsS | bash"
    )


def login_hint() -> str:
    return (
        "voice-cursor: Cursor CLI is not signed in. In a real terminal:\n"
        "  agent login\n"
        "  agent status\n"
        "Then: voice-cursor start --text\n"
        "Or set CURSOR_API_KEY / write it to ~/.cursor/api-key (author-typed, never shipped)."
    )


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("CURSOR_API_KEY", "").strip():
        key = load_api_key()
        if key:
            env["CURSOR_API_KEY"] = key
    return env


def cli_authenticated(binary: str) -> bool:
    """True if `agent status` is logged in, or an author-typed API key is present."""
    if os.environ.get("CURSOR_API_KEY", "").strip() or load_api_key():
        return True
    cmd = _launch_argv(binary) + ["status"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=45, env=_child_env()
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = f"{proc.stdout or ''}{proc.stderr or ''}"
    if "Not logged in" in text:
        return False
    return proc.returncode == 0


class CliRun:
    def __init__(
        self,
        proc: subprocess.Popen[str],
        chunks: list[str],
        agent,
        reader: threading.Thread | None = None,
    ) -> None:
        self._proc = proc
        self._chunks = chunks
        self._agent = agent
        self._reader = reader
        self.status = ""
        self._text = ""
        self._done = False

    def iter_text(self) -> Iterator[str]:
        while self._proc.poll() is None:
            yield ""
            time.sleep(0.1)
        self._finish()
        if self._text:
            yield self._text

    def wait(self) -> str:
        if self._proc.poll() is None:
            self._proc.wait()
        self._finish()
        return self._text

    def cancel(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._join_reader()

    def _join_reader(self) -> None:
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=5)

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._join_reader()
        raw = "".join(self._chunks)
        err = ""
        if self._proc.stderr is not None:
            try:
                err = self._proc.stderr.read() or ""
            except Exception:
                err = ""
        text, session = _parse_cli_json(raw)
        if session:
            self._agent._session = session
        if text:
            self._text = text
            return
        if self._proc.returncode not in (0, None):
            self.status = "error"
            self._text = (err or raw or "The Cursor CLI failed.").strip()
            return
        self._text = (raw or "").strip()


class CursorCliAgent:
    """Drive the Cursor CLI (`agent -p`) in this workspace. Follow-ups use --resume.

    Source: https://cursor.com/docs/cli/headless
    Does not use cursor_sdk.Agent.create. Does not click the IDE.
    """

    def __init__(self, cwd: str, binary: str | None = None) -> None:
        self._cwd = cwd
        self._bin = binary or find_agent_cli()
        if not self._bin:
            raise RuntimeError(install_hint())
        self._session: str | None = None
        self._primed = False
        self.agent_id = "cursor-cli"

    def send(self, prompt: str) -> CliRun:
        if not self._primed:
            prompt = VOICE_INSTRUCTION + "\n\n" + prompt
            self._primed = True
        cmd = _launch_argv(self._bin) + [
            "-p",
            "--force",
            "--trust",
            "--output-format",
            "json",
        ]
        if self._session:
            cmd.extend(["--resume", self._session])
        cmd.append(prompt)
        proc = subprocess.Popen(
            cmd,
            cwd=self._cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_child_env(),
        )
        chunks: list[str] = []

        def _read_stdout() -> None:
            try:
                if proc.stdout is None:
                    return
                for line in proc.stdout:
                    chunks.append(line)
            except Exception:
                pass

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        return CliRun(proc, chunks, self, reader)

    def close(self) -> None:
        pass


def _parse_cli_json(raw: str) -> tuple[str, str | None]:
    raw = raw.strip()
    if not raw:
        return "", None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Last JSON object if the CLI printed logs then JSON.
        start = raw.rfind("{")
        if start < 0:
            return raw, None
        try:
            data = json.loads(raw[start:])
        except json.JSONDecodeError:
            return raw, None
    if not isinstance(data, dict):
        return raw, None
    session = data.get("session_id") or data.get("sessionId")
    session_s = str(session) if session else None
    text = data.get("result") or ""
    if not text and data.get("type") == "result":
        text = str(data.get("result") or "")
    return str(text), session_s
