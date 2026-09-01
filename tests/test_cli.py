from pathlib import Path

from voice_cursor.cli import main
from voice_cursor.cursor_cli import _parse_cli_json, find_agent_cli


def test_start_help_exits_zero():
    try:
        main(["start", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit from --help")


def test_listen_test_help_exits_zero():
    try:
        main(["listen-test", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit from --help")


def test_listen_test_prints_heard(monkeypatch, capsys):
    monkeypatch.setattr(
        "voice_cursor.stt.listen_once", lambda timeout=45: "hey cursor microphone test"
    )
    assert main(["listen-test"]) == 0
    assert "hey cursor microphone test" in capsys.readouterr().out


def test_missing_cwd_is_one():
    assert main(["start", "--fake", "--cwd", "__no_such_dir__"]) == 1


def test_missing_agent_cli_is_one(monkeypatch):
    monkeypatch.setattr("voice_cursor.cursor_cli.find_agent_cli", lambda: None)
    assert main(["start", "--text", "--no-tts"]) == 1


def test_missing_talk_key_is_one(monkeypatch, tmp_path):
    monkeypatch.setattr("voice_cursor.cursor_cli.find_agent_cli", lambda: "agent.exe")
    monkeypatch.setattr("voice_cursor.cursor_cli.cli_authenticated", lambda _binary: True)

    class Dummy:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "voice_cursor.cursor_cli.CursorCliAgent",
        lambda cwd, binary=None: Dummy(),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(tmp_path / "no-home"))
    assert main(["start", "--text", "--no-tts", "--cwd", str(tmp_path)]) == 1


def test_parse_cli_json_result_and_session():
    raw = '{"type":"result","subtype":"success","result":"Done.","session_id":"abc-123"}'
    text, session = _parse_cli_json(raw)
    assert text == "Done."
    assert session == "abc-123"


def test_parse_cli_json_plain_text_fallback():
    text, session = _parse_cli_json("just a reply")
    assert text == "just a reply"
    assert session is None


def test_find_agent_cli_override(tmp_path: Path, monkeypatch):
    bin_path = tmp_path / "agent.exe"
    bin_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("VOICE_CURSOR_AGENT_BIN", str(bin_path))
    assert find_agent_cli() == str(bin_path)
