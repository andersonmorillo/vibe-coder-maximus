import threading
import time

import pytest

from voice_cursor.talk_mcp import (
    McpRun,
    McpTalkAgent,
    _READ_ONLY_FILESYSTEM_TOOLS,
    _filesystem_tool_allowed,
    talk_key_present,
)


def test_talk_key_present_reads_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert talk_key_present() is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert talk_key_present() is True


def test_filesystem_tool_allowlist_is_read_only():
    assert "read_text_file" in _READ_ONLY_FILESYSTEM_TOOLS
    assert _filesystem_tool_allowed("filesystem_read_text_file")
    assert _filesystem_tool_allowed("write_change_spec")
    assert not {
        "write_file",
        "edit_file",
        "create_directory",
        "move_file",
    } & _READ_ONLY_FILESYSTEM_TOOLS
    assert not _filesystem_tool_allowed("filesystem_write_file")


def test_mcp_talk_missing_key_fails_fast(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(tmp_path / "no-home"))
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        McpTalkAgent(cwd=str(tmp_path))


def test_mcp_run_ticks_then_emits_and_cancels():
    run = McpRun()

    def _produce() -> None:
        time.sleep(0.12)
        run._emit("hello")
        run._finish()

    threading.Thread(target=_produce, daemon=True).start()
    pieces = [p for p in run.iter_text()]
    assert "hello" in pieces
    assert any(p == "" for p in pieces)

    run2 = McpRun()
    run2.cancel()
    assert list(run2.iter_text()) == []
