import json
from types import SimpleNamespace

from voice_cursor.cursor_cli import (
    CursorCliAgent,
    _parse_cli_json,
    cli_authenticated,
    login_hint,
)
from voice_cursor.loop import VOICE_INSTRUCTION


def test_send_uses_print_force_json_and_resume(monkeypatch):
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(list(cmd))
            self.cmd = cmd
            self.stdout = iter(())
            self.stderr = SimpleNamespace(read=lambda: "")
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr("voice_cursor.cursor_cli.subprocess.Popen", FakePopen)
    agent = CursorCliAgent(cwd="C:\\proj", binary="agent.exe")
    payload = json.dumps(
        {"type": "result", "result": "Created the endpoint.", "session_id": "sess-1"}
    )
    run = agent.send("create a login endpoint")
    run._chunks.append(payload)
    assert "create a login endpoint" in "".join(calls[0])
    assert "-p" in calls[0]
    assert "--force" in calls[0]
    assert "--trust" in calls[0]
    assert "--resume" not in calls[0]
    assert list(run.iter_text()) == ["Created the endpoint."]
    assert agent._session == "sess-1"
    first = calls[0][-1]
    assert first.startswith(VOICE_INSTRUCTION)

    run2 = agent.send("add JWT")
    run2._chunks.append(
        json.dumps({"type": "result", "result": "Added JWT.", "session_id": "sess-1"})
    )
    assert "--resume" in calls[1]
    assert "sess-1" in calls[1]
    assert calls[1][-1] == "add JWT"


def test_cli_authenticated_env_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    assert cli_authenticated("agent.exe") is True


def test_cli_authenticated_not_logged_in(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr("voice_cursor.cursor_cli.load_api_key", lambda: "")

    class FakeRun:
        returncode = 0
        stdout = "Not logged in\n"
        stderr = ""

    monkeypatch.setattr(
        "voice_cursor.cursor_cli.subprocess.run", lambda *a, **k: FakeRun()
    )
    assert cli_authenticated("agent.exe") is False
    assert "agent login" in login_hint()


def test_send_passes_api_key_env(monkeypatch):
    seen: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen["env"] = kwargs.get("env") or {}
            self.stdout = iter(())
            self.stderr = SimpleNamespace(read=lambda: "")
            self.returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr("voice_cursor.cursor_cli.subprocess.Popen", FakePopen)
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    CursorCliAgent(cwd="C:\\proj", binary="agent.exe").send("hi")
    assert seen["env"].get("CURSOR_API_KEY") == "test-key"


def test_wait_joins_stdout_before_parse():
    """Process exit can beat the stdout thread; wait() must still see JSON."""
    import threading
    import time

    from voice_cursor.cursor_cli import CliRun

    class FakeProc:
        returncode = 0
        stderr = SimpleNamespace(read=lambda: "")

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    chunks: list[str] = []
    payload = json.dumps(
        {"type": "result", "result": "pong", "session_id": "sess-join"}
    )

    def _late() -> None:
        time.sleep(0.15)
        chunks.append(payload)

    reader = threading.Thread(target=_late)
    reader.start()
    agent = SimpleNamespace(_session=None)
    result = CliRun(FakeProc(), chunks, agent, reader).wait()
    assert result == "pong"
    assert agent._session == "sess-join"
