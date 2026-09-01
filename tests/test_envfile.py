from pathlib import Path

from voice_cursor.envfile import load_dotenv, load_talk_env, talk_llm


def test_load_dotenv_sets_missing_keys(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        'OPENROUTER_API_KEY="sk-or-test"\nOPENROUTER_MODEL=openai/gpt-4o-mini\n',
        encoding="utf-8",
    )
    load_dotenv(tmp_path / ".env")
    assert talk_llm()["api_key"] == "sk-or-test"
    assert talk_llm()["base_url"] == "https://openrouter.ai/api/v1"
    assert talk_llm()["model"] == "openai/gpt-4o-mini"
    assert talk_llm()["provider"] == "openai"


def test_load_dotenv_does_not_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "already")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=fromfile\n", encoding="utf-8")
    load_dotenv(tmp_path / ".env")
    assert talk_llm()["api_key"] == "already"


def test_openrouter_key_is_enough(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-x")
    spec = talk_llm()
    assert spec["provider"] == "openai"
    assert spec["api_key"] == "sk-or-v1-x"
    assert spec["base_url"] == "https://openrouter.ai/api/v1"


def test_openai_compat_openrouter_base(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-v1-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "anthropic/claude-sonnet-4")
    spec = talk_llm()
    assert spec["base_url"] == "https://openrouter.ai/api/v1"
    assert spec["model"] == "anthropic/claude-sonnet-4"


def test_global_env_used_when_cwd_has_none(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("OPENROUTER_API_KEY=sk-or-global\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(home))
    load_talk_env(project)
    assert talk_llm()["api_key"] == "sk-or-global"


def test_cwd_env_overrides_stale_process_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-stale-from-shell")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(home))
    load_talk_env(project)
    assert talk_llm()["api_key"] == "sk-or-v1-from-dotenv"


def test_cwd_env_wins_over_global(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("OPENROUTER_API_KEY=sk-or-global\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("OPENROUTER_API_KEY=sk-or-project\n", encoding="utf-8")
    monkeypatch.setenv("VOICE_CURSOR_HOME", str(home))
    load_talk_env(project)
    assert talk_llm()["api_key"] == "sk-or-project"


def test_placeholder_openrouter_key_is_ignored(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-your-key")
    assert talk_llm()["provider"] == ""


def test_apply_talk_credentials_overwrites_openai_key(monkeypatch):
    import os

    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-wrong")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-right")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    from voice_cursor.envfile import apply_talk_credentials

    spec = apply_talk_credentials()
    assert spec["api_key"] == "sk-or-v1-right"
    assert os.environ["OPENAI_API_KEY"] == "sk-or-v1-right"
    assert os.environ["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
