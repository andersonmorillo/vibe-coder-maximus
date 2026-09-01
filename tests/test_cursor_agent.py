from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from voice_cursor.cursor_agent import CursorSdkAgent, CursorRun
from voice_cursor.loop import VOICE_INSTRUCTION


def test_send_prefixes_voice_instruction_once(monkeypatch):
    fake_run = MagicMock()
    fake_run.iter_text.return_value = iter(["Created the endpoint."])
    fake_run.wait.return_value = SimpleNamespace(result="Created the endpoint.")
    fake_run.supports.return_value = True

    inner = MagicMock()
    inner.send.return_value = fake_run
    inner.__enter__.return_value = inner
    inner.__exit__.return_value = None
    inner.agent_id = "agent-local-test"
    inner.agent_id = "agent-local-test"

    created = {}

    class Agent:
        @staticmethod
        def create(**kwargs):
            created.update(kwargs)
            return inner

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(
        sys.modules,
        "cursor_sdk",
        SimpleNamespace(Agent=Agent, LocalAgentOptions=LocalAgentOptions),
    )

    agent = CursorSdkAgent(cwd="C:\\proj", api_key="cursor_test")
    assert created["api_key"] == "cursor_test"
    assert created["model"] == "composer-2.5"
    assert "cloud" not in created
    assert created["local"].kwargs["cwd"] == "C:\\proj"
    assert created["local"].kwargs["setting_sources"] == ["user", "project"]

    run = agent.send("create a login endpoint")
    first = inner.send.call_args[0][0]
    assert first.startswith(VOICE_INSTRUCTION)
    assert first.endswith("create a login endpoint")
    assert list(run.iter_text()) == ["Created the endpoint."]
    assert run.wait() == "Created the endpoint."

    agent.send("add JWT")
    second = inner.send.call_args[0][0]
    assert second == "add JWT"
    assert VOICE_INSTRUCTION not in second

    run.cancel()
    inner.__exit__.assert_not_called()
    agent.close()
    inner.__exit__.assert_called_once()


def test_refuses_cloud_agent_id(monkeypatch):
    inner = MagicMock()
    inner.__enter__.return_value = inner
    inner.__exit__.return_value = None
    inner.agent_id = "bc-cloud-vm"

    class Agent:
        @staticmethod
        def create(**kwargs):
            return inner

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setitem(
        sys.modules,
        "cursor_sdk",
        SimpleNamespace(Agent=Agent, LocalAgentOptions=LocalAgentOptions),
    )
    try:
        CursorSdkAgent(cwd=".", api_key="cursor_test")
        raise AssertionError("expected RuntimeError for cloud agent")
    except RuntimeError as exc:
        assert "cloud agent" in str(exc).lower()
    inner.__exit__.assert_called()


def test_windows_bridge_reader_patches_311(monkeypatch):
    from voice_cursor.cursor_agent import install_windows_bridge_reader

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(os, "get_blocking", raising=False)
    monkeypatch.delattr(os, "set_blocking", raising=False)
    install_windows_bridge_reader()
    import cursor_sdk._bridge as br

    assert getattr(br._read_discovery, "_voice_cursor_patched", False)


def test_bridge_argv_uses_path_node_when_wheel_omits_exe(monkeypatch, tmp_path):
    from pathlib import Path

    import cursor_sdk._vendor as vendor
    from voice_cursor.cursor_agent import bridge_argv

    js = tmp_path / "dist" / "bin" / "cursor-sdk-bridge.js"
    js.parent.mkdir(parents=True)
    js.write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(vendor, "_BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "voice_cursor.cursor_agent.shutil.which",
        lambda name: r"C:\nodejs\node.exe",
    )
    argv = bridge_argv()
    assert argv is not None
    assert Path(argv[0]).name == "node.exe"
    assert Path(argv[1]).name == "cursor-sdk-bridge.js"
