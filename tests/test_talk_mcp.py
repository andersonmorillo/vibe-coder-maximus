import pytest

from voice_cursor.talk_mcp import McpTalkAgent, talk_key_present


def test_talk_key_present_reads_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert talk_key_present() is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert talk_key_present() is True


def test_mcp_talk_missing_key_fails_fast(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(tmp_path / "no-home"))
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        McpTalkAgent(cwd=str(tmp_path))
