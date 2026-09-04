from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from voice_cursor.firstmate import (
    FirstmateAgent,
    apply_inbox_body,
    resolve_firstmate_root,
)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "firstmate"
    (root / "bin").mkdir(parents=True)
    (root / ".cursor").mkdir()
    (root / "AGENTS.md").write_text("# Firstmate\n", encoding="utf-8")
    (root / "bin" / "fm-inbox.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bin" / "fm-sessionstart-cursor.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    (root / ".cursor" / "hooks.json").write_text("{}", encoding="utf-8")
    return root


def test_resolve_firstmate_root_walks_from_project(tmp_path: Path):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)

    assert resolve_firstmate_root(cwd=project) == root


def test_resolve_firstmate_root_uses_legacy_environment_alias(
    tmp_path: Path, monkeypatch
):
    root = _root(tmp_path)
    project = tmp_path / "other-project"
    project.mkdir()
    monkeypatch.delenv("VOICE_CURSOR_FIRSTMATE_ROOT", raising=False)
    monkeypatch.setenv("FIRSTMATE_ROOT", str(root))

    assert resolve_firstmate_root(cwd=project) == root


def test_explicit_firstmate_root_wins_over_environment(
    tmp_path: Path, monkeypatch
):
    explicit = _root(tmp_path / "explicit")
    configured = _root(tmp_path / "configured")
    monkeypatch.setenv("VOICE_CURSOR_FIRSTMATE_ROOT", str(configured))

    assert resolve_firstmate_root(explicit, cwd=tmp_path) == explicit


def _route_run(calls: list, *, has_session=1, lock="lock: free\n", launch=0, note=0):
    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        joined = " ".join(str(part) for part in command)
        if "has-session" in joined:
            return SimpleNamespace(returncode=has_session, stdout="", stderr="")
        if "fm-lock.sh" in joined:
            return SimpleNamespace(returncode=0, stdout=lock, stderr="")
        if "new-session" in joined:
            return SimpleNamespace(
                returncode=launch,
                stdout="",
                stderr="duplicate session" if launch else "",
            )
        if "note" in joined:
            return SimpleNamespace(
                returncode=note, stdout="queued note\n", stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_apply_inbox_body_includes_workspace_and_spec(tmp_path: Path):
    project = tmp_path / "talk-to-cursor"
    spec = "Add a README sentence about apply."
    body = apply_inbox_body(project, spec)
    assert str(project) in body
    assert spec in body
    assert "voice-cursor apply" in body
    assert "Do not edit the launch folder" in body


def test_firstmate_start_launches_trusted_primary_in_tmux(
    tmp_path: Path, monkeypatch
):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        "voice_cursor.firstmate.subprocess.run", _route_run(calls)
    )
    agent = FirstmateAgent(
        str(project),
        firstmate_root=root,
        firstmate_home=tmp_path / "home",
        binary="cursor-agent",
        model="gpt-test",
    )
    agent.start()

    launch = next(command for command, _ in calls if "new-session" in command)
    assert launch[:7] == [
        "/usr/bin/tmux",
        "new-session",
        "-d",
        "-s",
        agent.session,
        "-c",
        str(root),
    ]
    assert launch[-4:] == [
        "cursor-agent",
        "--trust",
        "--model",
        "gpt-test",
    ]
    assert any(kwargs["env"]["FM_HOME"] == str(tmp_path / "home") for _, kwargs in calls)
    assert "session" in agent.startup_message


def test_firstmate_start_reuses_existing_tmux_session(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        "voice_cursor.firstmate.subprocess.run",
        _route_run(calls, has_session=0),
    )
    agent = FirstmateAgent(
        str(project), firstmate_root=root, binary="cursor-agent"
    )
    agent.start()
    assert all("new-session" not in command for command, _ in calls)
    assert "using existing Firstmate primary" in agent.startup_message


def test_firstmate_start_skips_launch_when_fleet_owned(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    (root / "bin" / "fm-lock.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        "voice_cursor.firstmate.subprocess.run",
        _route_run(calls, lock="lock: held by live harness pid 9176\n"),
    )
    agent = FirstmateAgent(
        str(project), firstmate_root=root, binary="cursor-agent"
    )
    agent.start()
    assert all("new-session" not in command for command, _ in calls)
    assert "already owned" in agent.startup_message
    run = agent.send("Add a README sentence about apply.")
    note = next(kwargs for command, kwargs in calls if command[-2:] == ["note", "-"])
    assert str(project) in note["input"]
    assert "Add a README sentence about apply." in note["input"]
    assert "voice-cursor apply" in note["input"]
    assert list(run.iter_text()) == [
        "Queued for Firstmate. It will route the project work and report back there."
    ]


def test_firstmate_start_queues_when_launch_loses_the_fleet(
    tmp_path: Path, monkeypatch
):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        "voice_cursor.firstmate.subprocess.run",
        _route_run(calls, launch=1),
    )
    agent = FirstmateAgent(
        str(project), firstmate_root=root, binary="cursor-agent"
    )
    agent.start()
    assert "Not starting a second primary" in agent.startup_message
    agent.send("Add a README sentence about apply.")
    note = next(kwargs for command, kwargs in calls if command[-2:] == ["note", "-"])
    assert str(project) in note["input"]
    assert "Add a README sentence about apply." in note["input"]


def test_firstmate_send_queues_request_in_inbox(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )

    monkeypatch.setattr(
        "voice_cursor.firstmate.subprocess.run",
        _route_run(calls, has_session=0),
    )
    agent = FirstmateAgent(
        str(project),
        firstmate_root=root,
        binary="cursor-agent",
    )
    agent.start()
    run = agent.send("add a login endpoint")

    command, kwargs = calls[-1]
    assert Path(command[-3]).name == "fm-inbox.sh"
    assert command[-2:] == ["note", "-"]
    assert "Project: demo" in kwargs["input"]
    assert str(project) in kwargs["input"]
    assert "add a login endpoint" in kwargs["input"]
    assert "voice-cursor apply" in kwargs["input"]
    assert "Do not edit the launch folder" in kwargs["input"]
    assert list(run.iter_text()) == [
        "Queued for Firstmate. It will route the project work and report back there."
    ]


def test_invalid_firstmate_root_explains_configuration(tmp_path: Path):
    with pytest.raises(RuntimeError, match="--firstmate-root"):
        resolve_firstmate_root(tmp_path / "missing")
