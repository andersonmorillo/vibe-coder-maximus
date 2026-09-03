from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from voice_cursor.firstmate import FirstmateAgent, resolve_firstmate_root


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

    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("voice_cursor.firstmate.subprocess.run", run)
    agent = FirstmateAgent(
        str(project),
        firstmate_root=root,
        firstmate_home=tmp_path / "home",
        binary="cursor-agent",
        model="gpt-test",
    )
    agent.start()

    command, kwargs = calls[-1]
    assert command[:7] == [
        "/usr/bin/tmux",
        "new-session",
        "-d",
        "-s",
        agent.session,
        "-c",
        str(root),
    ]
    assert command[-4:] == [
        "cursor-agent",
        "--trust",
        "--model",
        "gpt-test",
    ]
    assert kwargs["env"]["FM_HOME"] == str(tmp_path / "home")
    assert "session" in agent.startup_message


def test_firstmate_send_queues_request_in_inbox(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    project = root / "projects" / "demo"
    project.mkdir(parents=True)
    calls: list[tuple[list[str], dict]] = []

    monkeypatch.setattr(
        "voice_cursor.firstmate.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )

    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=0, stdout="queued note\n", stderr="")

    monkeypatch.setattr("voice_cursor.firstmate.subprocess.run", run)
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
    assert list(run.iter_text()) == [
        "Queued for Firstmate. It will route the project work and report back there."
    ]


def test_invalid_firstmate_root_explains_configuration(tmp_path: Path):
    with pytest.raises(RuntimeError, match="--firstmate-root"):
        resolve_firstmate_root(tmp_path / "missing")
