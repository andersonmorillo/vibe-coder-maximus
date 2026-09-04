from pathlib import Path

from voice_cursor.doctor import doctor_lines, run_doctor


def test_doctor_missing_key_is_one(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(tmp_path / "no-home"))
    monkeypatch.setattr("voice_cursor.doctor.find_agent_cli", lambda: None)
    monkeypatch.setattr("voice_cursor.doctor.cuda_device_count", lambda: 1)
    monkeypatch.setattr(
        "voice_cursor.stt.describe_input_devices", lambda selected=None: "  [0] fake"
    )
    assert run_doctor(tmp_path) == 1
    out = capsys.readouterr().out
    assert "talk key: missing" in out
    assert "cuda devices: 1" in out
    assert "on cuda" in out


def test_doctor_lines_include_stt_and_talk(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-zzzzzzzzzzzztest")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(tmp_path / "no-home"))
    monkeypatch.setattr("voice_cursor.doctor.find_agent_cli", lambda: None)
    monkeypatch.setattr("voice_cursor.doctor.cuda_device_count", lambda: 0)
    monkeypatch.setattr(
        "voice_cursor.stt.describe_input_devices", lambda selected=None: "  [0] fake"
    )
    monkeypatch.setattr(
        "voice_cursor.doctor._ping_openrouter", lambda *args, **kwargs: "ok (1 models)"
    )
    lines = "\n".join(doctor_lines(tmp_path))
    assert "talk:" in lines
    assert "...test" in lines
    assert "on cpu" in lines
    assert "sk-or-v1-zzzzzzzzzzzztest" not in lines
