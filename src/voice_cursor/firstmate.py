from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from voice_cursor.cursor_cli import _launch_argv, find_agent_cli


_ROOT_FILES = (
    Path("AGENTS.md"),
    Path("bin") / "fm-inbox.sh",
    Path("bin") / "fm-sessionstart-cursor.sh",
    Path(".cursor") / "hooks.json",
)
_SESSION_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _configured_path(
    explicit: str | Path | None,
    *environment_names: str,
) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit)
    for name in environment_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _looks_like_firstmate(root: Path) -> bool:
    return all((root / path).is_file() for path in _ROOT_FILES)


def resolve_firstmate_root(
    root: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
) -> Path:
    configured = _configured_path(root, "VOICE_CURSOR_FIRSTMATE_ROOT")
    if configured:
        resolved = Path(configured).expanduser().resolve()
    else:
        base = Path(cwd or Path.cwd()).expanduser().resolve()
        resolved = next(
            (candidate for candidate in (base, *base.parents) if _looks_like_firstmate(candidate)),
            base,
        )
    if not _looks_like_firstmate(resolved):
        missing = ", ".join(
            str(path) for path in _ROOT_FILES if not (resolved / path).is_file()
        )
        raise RuntimeError(
            f"not a Firstmate checkout: {resolved} (missing {missing}). "
            "Set --firstmate-root or VOICE_CURSOR_FIRSTMATE_ROOT."
        )
    return resolved


def resolve_firstmate_home(
    root: str | Path,
    home: str | Path | None = None,
) -> Path:
    configured = _configured_path(
        home,
        "VOICE_CURSOR_FIRSTMATE_HOME",
        "FM_HOME",
    )
    return (Path(configured).expanduser() if configured else Path(root)).resolve()


def primary_session_name(root: Path, home: Path, configured: str = "") -> str:
    if configured.strip():
        if not _SESSION_NAME.fullmatch(configured):
            raise RuntimeError(
                "Firstmate session name must contain only letters, numbers, "
                "periods, underscores, or hyphens."
            )
        return configured
    digest = hashlib.sha256(f"{root}\0{home}".encode()).hexdigest()[:10]
    return f"firstmate-{digest}"


def _command_detail(proc) -> str:
    text = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
    return text.splitlines()[-1] if text else "the command returned an error"


class FirstmateRun:
    def __init__(self, text: str) -> None:
        self._text = text
        self.status = ""

    def iter_text(self) -> Iterator[str]:
        if self._text:
            yield self._text

    def wait(self) -> str:
        return self._text

    def cancel(self) -> None:
        pass


class FirstmateAgent:
    """Launch a Firstmate primary and queue requests into its captain inbox."""

    apply_message = "Handing to Firstmate."
    uses_request_text = True

    def __init__(
        self,
        cwd: str,
        *,
        firstmate_root: str | Path | None = None,
        firstmate_home: str | Path | None = None,
        session: str = "",
        binary: str | None = None,
        model: str | None = None,
    ) -> None:
        self._project = Path(cwd).expanduser().resolve()
        self.root = resolve_firstmate_root(firstmate_root, cwd=self._project)
        self.home = resolve_firstmate_home(self.root, firstmate_home)
        self.session = primary_session_name(self.root, self.home, session)
        self.binary = binary or os.environ.get(
            "VOICE_CURSOR_FIRSTMATE_AGENT_BIN", ""
        ).strip() or find_agent_cli()
        if not self.binary:
            raise RuntimeError(
                "Cursor Agent CLI is required to launch the Firstmate primary. "
                "Install it or pass --agent-bin."
            )
        self._tmux = shutil.which("tmux")
        if not self._tmux:
            raise RuntimeError(
                "tmux is required to launch the Firstmate primary. "
                "Install tmux and retry."
            )
        self.model = (
            model
            or os.environ.get("VOICE_CURSOR_FIRSTMATE_MODEL", "").strip()
            or None
        )
        self._env = os.environ.copy()
        self._env["FM_ROOT_OVERRIDE"] = str(self.root)
        self._env["FM_HOME"] = str(self.home)
        self._started = False
        self.startup_message = ""

    @property
    def primary_command(self) -> list[str]:
        command = _launch_argv(self.binary) + ["--trust"]
        if self.model:
            command.extend(["--model", self.model])
        return command

    def start(self) -> None:
        if self._started:
            return
        target = [self._tmux, "has-session", "-t", self.session]
        existing = subprocess.run(
            target,
            cwd=str(self.root),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )
        if existing.returncode == 0:
            self._started = True
            self.startup_message = (
                f"using existing Firstmate primary in tmux session {self.session}; "
                f"attach with: tmux attach -t {self.session}"
            )
            return

        launch = subprocess.run(
            [
                self._tmux,
                "new-session",
                "-d",
                "-s",
                self.session,
                "-c",
                str(self.root),
                "--",
                *self.primary_command,
            ],
            cwd=str(self.root),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )
        if launch.returncode != 0:
            raise RuntimeError(
                f"could not launch the Firstmate primary: {_command_detail(launch)}"
            )
        self._started = True
        self.startup_message = (
            f"Firstmate primary started in tmux session {self.session}; "
            f"attach with: tmux attach -t {self.session}"
        )

    def send(self, prompt: str) -> FirstmateRun:
        if not self._started:
            raise RuntimeError("Firstmate primary has not been started")
        request = (
            f"Project: {self._project.name}\n"
            f"Workspace: {self._project}\n\n"
            f"{prompt.strip()}"
        )
        inbox = self.root / "bin" / "fm-inbox.sh"
        command = [str(inbox), "note", "-"]
        if not os.access(inbox, os.X_OK):
            command.insert(0, shutil.which("bash") or "bash")
        try:
            queued = subprocess.run(
                command,
                cwd=str(self.root),
                env=self._env,
                input=request + "\n",
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Firstmate did not confirm the request before the 30-second timeout"
            ) from exc
        if queued.returncode != 0:
            raise RuntimeError(
                f"could not queue the request for Firstmate: {_command_detail(queued)}"
            )
        return FirstmateRun(
            "Queued for Firstmate. It will route the project work and report back there."
        )

    def close(self) -> None:
        # The primary belongs to Firstmate and must outlive this voice frontend.
        pass
