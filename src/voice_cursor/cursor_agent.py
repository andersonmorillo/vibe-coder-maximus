from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterator

from voice_cursor.loop import VOICE_INSTRUCTION
from voice_cursor.ports import Run


def install_windows_bridge_reader() -> None:
    """cursor-sdk reads bridge stderr with os.get_blocking; Python 3.11 Windows has neither."""
    if sys.platform != "win32":
        return
    if hasattr(os, "get_blocking") and hasattr(os, "set_blocking"):
        return
    try:
        import cursor_sdk._bridge as br
    except Exception:
        return
    if getattr(br._read_discovery, "_voice_cursor_patched", False):
        return

    def _read_discovery(process, timeout: float):
        import threading

        from cursor_sdk._bridge import parse_discovery_line
        from cursor_sdk.errors import CursorSDKError

        if process.stderr is None:
            raise CursorSDKError("Bridge process stderr is unavailable")
        found: dict = {}
        lines: list[str] = []

        def reader() -> None:
            try:
                for line in process.stderr:
                    lines.append(line)
                    discovery = parse_discovery_line(line)
                    if discovery is not None:
                        found["d"] = discovery
                        return
            except Exception as exc:
                found["e"] = exc

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)
        if "d" in found:
            return found["d"]
        if "e" in found:
            raise found["e"]
        tail = "".join(lines)
        exit_code = process.poll()
        if exit_code is not None:
            raise CursorSDKError(
                f"Bridge exited before discovery with status {exit_code}: {tail}"
            )
        raise CursorSDKError("Timed out waiting for bridge discovery")

    _read_discovery._voice_cursor_patched = True  # type: ignore[attr-defined]
    br._read_discovery = _read_discovery


def bridge_argv() -> list[str] | None:
    """PATH node + bundled JS when the wheel's node.exe is missing.

    Windows cursor-sdk launcher is `bin/cursor-sdk-bridge.cmd` which calls
    `%~dp0node.exe`. Some wheels omit that binary. System `node` still works.
    """
    try:
        from cursor_sdk._vendor import _BRIDGE_DIR
    except Exception:
        return None
    root = Path(_BRIDGE_DIR)
    js = root / "dist" / "bin" / "cursor-sdk-bridge.js"
    bundled_node = root / "bin" / "node.exe"
    if not js.is_file():
        return None
    if sys.platform == "win32" and not bundled_node.is_file():
        node = shutil.which("node")
        if not node:
            return None
        return [node, str(js)]
    return None


class CursorRun:
    def __init__(self, run) -> None:
        self._run = run
        self.status = ""

    def iter_text(self) -> Iterator[str]:
        # Source: https://cursor.com/docs/sdk/python — run.messages() / run.iter_text()
        iter_text = getattr(self._run, "iter_text", None)
        if iter_text is not None:
            yield from iter_text()
            return
        for message in self._run.messages():
            if getattr(message, "type", None) != "assistant":
                continue
            content = getattr(getattr(message, "message", None), "content", ())
            for block in content:
                if getattr(block, "type", None) == "text":
                    yield getattr(block, "text", "")

    def wait(self) -> str:
        result = self._run.wait()
        if isinstance(result, str):
            return result
        self.status = str(getattr(result, "status", "") or "")
        return getattr(result, "result", None) or ""

    def cancel(self) -> None:
        try:
            if self._run.supports("cancel"):
                self._run.cancel()
        except Exception:
            pass


class CursorSdkAgent:
    """Local Cursor agent only. Edits the author's disk. Never a cloud VM.

    Source: https://cursor.com/docs/sdk/python
    Agent.create(..., local=LocalAgentOptions(cwd=...)). Do not pass cloud=.
    Cloud agent ids start with bc-; we refuse those.
    """

    def __init__(self, cwd: str, api_key: str | None = None) -> None:
        from cursor_sdk import Agent, LocalAgentOptions

        key = (api_key or os.environ.get("CURSOR_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("CURSOR_API_KEY is missing")
        install_windows_bridge_reader()
        self._owned_client = None
        self._cm = None
        self._agent = None
        local = LocalAgentOptions(cwd=cwd, setting_sources=["user", "project"])
        Client = getattr(sys.modules["cursor_sdk"], "Client", None)
        cmd = bridge_argv()
        try:
            if Client is not None and cmd is not None:
                self._owned_client = Client.launch_bridge(
                    command=cmd, workspace=cwd
                )
                created = Agent.create(
                    model="composer-2.5",
                    api_key=key,
                    local=local,
                    client=self._owned_client,
                )
                self._cm = created
                enter = getattr(created, "__enter__", None)
                self._agent = enter() if enter is not None else created
            else:
                self._cm = Agent.create(
                    model="composer-2.5",
                    api_key=key,
                    local=local,
                )
                self._agent = self._cm.__enter__()
        except Exception:
            self.close()
            raise
        agent_id = str(getattr(self._agent, "agent_id", "") or "")
        if agent_id.startswith("bc-"):
            self.close()
            raise RuntimeError(
                "voice-cursor refused a cloud agent (id starts with bc-). "
                "This CLI only runs a local agent against your workspace."
            )
        self._primed = False
        self.agent_id = agent_id

    def send(self, prompt: str) -> Run:
        if not self._primed:
            prompt = VOICE_INSTRUCTION + "\n\n" + prompt
            self._primed = True
        return CursorRun(self._agent.send(prompt))

    def close(self) -> None:
        try:
            if self._cm is not None:
                exit_cm = getattr(self._cm, "__exit__", None)
                if exit_cm is not None:
                    exit_cm(None, None, None)
                else:
                    closer = getattr(self._agent, "close", None)
                    if closer is not None:
                        closer()
        finally:
            self._cm = None
            if self._owned_client is not None:
                try:
                    self._owned_client.close()
                except Exception:
                    pass
                self._owned_client = None
