"""Talk port backed by lastmile-ai mcp-agent (local MCPApp, not mcp-c).

Sources:
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/agents.md
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/mcpapp.md
"""

from __future__ import annotations

import asyncio
from typing import Iterator

from voice_cursor.envfile import apply_talk_credentials, load_cwd_dotenv, talk_llm
from voice_cursor.spec import write_spec

TALK_INSTRUCTION = (
    "You are a voice coding assistant. Keep replies to 2-4 short spoken "
    "sentences. No code fences. If the user wants a code change, call "
    "write_change_spec with a clear instruction for Cursor. Do not claim "
    "you edited the repo. The user must say apply to run Cursor CLI."
)


def talk_key_present() -> bool:
    return bool(talk_llm()["api_key"])


def install_hint() -> str:
    return (
        "voice-cursor: mcp-agent is missing. Install with: "
        'pip install -e ".[talk]"'
    )


def key_hint() -> str:
    return (
        "voice-cursor: talk LLM key missing. Put OPENROUTER_API_KEY in "
        "%USERPROFILE%\\.voice-cursor\\.env (or .env in --cwd). Never commit .env."
    )


class McpRun:
    def __init__(self, text: str) -> None:
        self._text = text
        self.status = ""
        self._cancelled = False

    def iter_text(self) -> Iterator[str]:
        if not self._cancelled and self._text:
            yield self._text

    def wait(self) -> str:
        return "" if self._cancelled else self._text

    def cancel(self) -> None:
        self._cancelled = True


class McpTalkAgent:
    """mcp-agent Agent + AugmentedLLM. May write only the spec file."""

    def __init__(self, cwd: str) -> None:
        load_cwd_dotenv(cwd)
        apply_talk_credentials()
        if not talk_key_present():
            raise RuntimeError(key_hint())
        try:
            from mcp_agent.agents.agent import Agent
            from mcp_agent.app import MCPApp
        except ImportError as exc:
            raise RuntimeError(install_hint()) from exc
        self._cwd = cwd
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._app_cm = None
        self._agent_cm = None
        self._llm = None
        self.agent_id = "mcp-agent-talk"
        try:
            self._loop.run_until_complete(self._boot(MCPApp, Agent))
        except Exception:
            self.close()
            raise

    def _write_change_spec(self, text: str) -> str:
        """Save a code-change request. User must say apply to run Cursor."""
        write_spec(self._cwd, text)
        return (
            "Spec saved. Tell the user to say apply when they want "
            "Cursor to edit the project."
        )

    async def _boot(self, MCPApp, Agent) -> None:
        from mcp_agent.config import OpenAISettings, Settings

        spec = talk_llm()
        kwargs: dict = {}
        if spec["provider"] == "openai":
            openai_kw: dict = {"api_key": spec["api_key"]}
            if spec["base_url"]:
                openai_kw["base_url"] = spec["base_url"]
            if spec["model"]:
                openai_kw["default_model"] = spec["model"]
            if "openrouter.ai" in (spec["base_url"] or ""):
                openai_kw["default_headers"] = {
                    "HTTP-Referer": "https://github.com/voice-cursor",
                    "X-Title": "voice-cursor",
                }
            kwargs["openai"] = OpenAISettings(_env_file=None, **openai_kw)
        settings = Settings(_env_file=None, **kwargs)
        app = MCPApp(name="voice-cursor-talk", settings=settings)
        self._app_cm = app.run()
        running = await self._app_cm.__aenter__()
        agent = Agent(
            name="talk",
            instruction=TALK_INSTRUCTION,
            functions=[self._write_change_spec],
            context=running.context,
        )
        self._agent_cm = agent
        await agent.__aenter__()
        if spec["provider"] == "openai":
            from mcp_agent.workflows.llm.augmented_llm_openai import (
                OpenAIAugmentedLLM,
            )

            llm_cls = OpenAIAugmentedLLM
        else:
            from mcp_agent.workflows.llm.augmented_llm_anthropic import (
                AnthropicAugmentedLLM,
            )

            llm_cls = AnthropicAugmentedLLM
        self._llm = await agent.attach_llm(llm_cls)

    def send(self, prompt: str) -> McpRun:
        if self._llm is None:
            raise RuntimeError("mcp-agent talk is not started")
        try:
            text = self._loop.run_until_complete(self._llm.generate_str(prompt))
        except Exception as exc:
            err = str(exc)
            if "401" in err or "User not found" in err:
                raise RuntimeError(
                    "OpenRouter rejected the talk key (401). "
                    "Check OPENROUTER_API_KEY in --cwd/.env "
                    "(or %USERPROFILE%\\.voice-cursor\\.env)."
                ) from exc
            raise
        return McpRun(str(text or ""))

    def close(self) -> None:
        if self._loop.is_closed():
            return

        async def _shutdown() -> None:
            if self._agent_cm is not None:
                await self._agent_cm.__aexit__(None, None, None)
                self._agent_cm = None
            if self._app_cm is not None:
                await self._app_cm.__aexit__(None, None, None)
                self._app_cm = None

        try:
            if self._loop.is_running():
                return
            self._loop.run_until_complete(_shutdown())
        except Exception:
            pass
        finally:
            self._llm = None
            self._loop.close()
