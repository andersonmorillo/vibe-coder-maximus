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
    configured = _configured_path(
        root,
        "VOICE_CURSOR_FIRSTMATE_ROOT",
        "FIRSTMATE_ROOT",
    )
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
            "Set --firstmate-root, VOICE_CURSOR_FIRSTMATE_ROOT, "
            "or FIRSTMATE_ROOT."
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


def apply_inbox_body(project: Path, spec: str) -> str:
    return (
        "This is a voice-cursor apply. Spawn or steer a worker for this "
        "project. Do not edit the launch folder from the voice process.\n"
        f"\nProject: {project.name}\n"
        f"Workspace: {project}\n"
        f"\n{spec.strip()}\n"
    )


def _script_argv(script: Path, *args: str) -> list[str]:
    command = [str(script), *args]
    if not os.access(script, os.X_OK):
        command.insert(0, shutil.which("bash") or "bash")
    return command


def _launch_looks_owned(detail: str) -> bool:
    lower = detail.lower()
    return (
        "held by live harness" in lower
        or "duplicate session" in lower
        or "already owned" in lower
    )


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

    def _ready(self, message: str) -> None:
        self._started = True
        self.startup_message = message

    def _run(self, command: list[str], **kwargs):
        return subprocess.run(
            command,
            cwd=str(self.root),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
            **kwargs,
        )

    def _fleet_owned(self) -> bool:
        lock = self.root / "bin" / "fm-lock.sh"
        if not lock.is_file():
            return False
        status = self._run(_script_argv(lock, "status"))
        return "held by live harness" in (status.stdout or "")

    def start(self) -> None:
        if self._started:
            return
        existing = self._run(
            [self._tmux, "has-session", "-t", self.session]
        )
        if existing.returncode == 0:
            self._ready(
                f"using existing Firstmate primary in tmux session {self.session}; "
                f"attach with: tmux attach -t {self.session}"
            )
            return
        if self._fleet_owned():
            self._ready(
                "Firstmate is already owned by another session; "
                "requests will be queued in the inbox for that session. "
                "Not starting a second primary."
            )
            return

        launch = self._run(
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
            ]
        )
        if launch.returncode != 0:
            detail = _command_detail(launch)
            if self._fleet_owned() or _launch_looks_owned(detail):
                self._ready(
                    f"could not launch a Firstmate primary ({detail}); "
                    "requests will be queued in the inbox for the existing session. "
                    "Not starting a second primary."
                )
                return
            raise RuntimeError(
                f"could not launch the Firstmate primary: {detail}"
            )
        self._ready(
            f"Firstmate primary started in tmux session {self.session}; "
            f"attach with: tmux attach -t {self.session}"
        )

    def send(self, prompt: str) -> FirstmateRun:
        if not self._started:
            raise RuntimeError("Firstmate primary has not been started")
        request = apply_inbox_body(self._project, prompt)
        inbox = self.root / "bin" / "fm-inbox.sh"
        command = _script_argv(inbox, "note", "-")
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
