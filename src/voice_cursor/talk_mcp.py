"""Talk port backed by lastmile-ai mcp-agent (local MCPApp, not mcp-c).

Sources:
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/agents.md
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/mcpapp.md
"""

from __future__ import annotations

import asyncio
import json
import threading
from queue import Empty, Queue
from typing import Iterator

from voice_cursor.envfile import apply_talk_credentials, load_cwd_dotenv, talk_llm
from voice_cursor.spec import write_spec

TALK_INSTRUCTION = (
    "You are a voice coding assistant. Keep replies to 2-4 short spoken "
    "sentences. No code fences. If the user wants a code change, call "
    "write_change_spec with a clear instruction for Cursor. Do not claim "
    "you edited the repo. The user must say apply to run Cursor CLI."
)

_WRITE_SPEC_TOOL = {
    "type": "function",
    "function": {
        "name": "write_change_spec",
        "description": (
            "Save a code-change request. The user must say apply before Cursor edits."
        ),
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}


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
    def __init__(self) -> None:
        self.status = ""
        self._cancelled = False
        self._text = ""
        self._q: Queue[str | None] = Queue()
        self._error: BaseException | None = None
        self._fut: asyncio.Future | None = None

    def iter_text(self) -> Iterator[str]:
        while True:
            if self._cancelled:
                return
            try:
                item = self._q.get(timeout=0.1)
            except Empty:
                yield ""
                continue
            if item is None:
                break
            if item:
                yield item
        if self._error and not self._cancelled:
            raise self._error

    def wait(self) -> str:
        if self._fut is not None:
            try:
                self._fut.result()
            except Exception:
                pass
        if self._cancelled:
            return ""
        if self._error:
            raise self._error
        return self._text

    def cancel(self) -> None:
        self._cancelled = True
        if self._fut is not None and not self._fut.done():
            self._fut.cancel()
        self._q.put(None)

    def _emit(self, piece: str) -> None:
        if piece and not self._cancelled:
            self._text += piece
            self._q.put(piece)

    def _finish(self, err: BaseException | None = None) -> None:
        if err is not None and not self._cancelled:
            self._error = err
            self.status = "error"
        self._q.put(None)


class McpTalkAgent:
    """mcp-agent Agent + streaming OpenAI-compatible talk. May write only the spec file."""

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
        self._history: list[dict] = []
        self._loop = asyncio.new_event_loop()
        self._app_cm = None
        self._agent_cm = None
        self._llm = None
        self._boot_err: BaseException | None = None
        self.agent_id = "mcp-agent-talk"
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, args=(MCPApp, Agent), daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=120):
            self.close()
            raise RuntimeError("mcp-agent talk failed to start")
        if self._boot_err is not None:
            self.close()
            raise self._boot_err

    def _thread_main(self, MCPApp, Agent) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot(MCPApp, Agent))
        except BaseException as exc:
            self._boot_err = exc
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    def _write_change_spec(self, text: str) -> str:
        """Save a code-change request. User must say apply to run Cursor."""
        write_spec(self._cwd, text)
        return (
            "Spec saved. Tell the user to say apply when they want "
            "Cursor to edit the project."
        )

    async def _boot(self, MCPApp, Agent) -> None:
        from mcp_agent.config import LoggerSettings, OpenAISettings, Settings

        spec = talk_llm()
        kwargs: dict = {
            "logger": LoggerSettings(
                type="none",
                transports=["none"],
                level="error",
                progress_display=False,
            ),
        }
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

    async def _talk_once(self, prompt: str, run: McpRun) -> None:
        try:
            spec = talk_llm()
            if spec["provider"] == "openai":
                await self._stream_openai(prompt, run)
            else:
                await self._generate_fallback(prompt, run)
        except asyncio.CancelledError:
            run._finish()
            raise
        except BaseException as exc:
            err = str(exc)
            if "401" in err or "User not found" in err:
                run._finish(
                    RuntimeError(
                        "OpenRouter rejected the talk key (401). "
                        "Check OPENROUTER_API_KEY in --cwd/.env "
                        "(or %USERPROFILE%\\.voice-cursor\\.env)."
                    )
                )
            else:
                run._finish(exc)
        else:
            run._finish()

    async def _generate_fallback(self, prompt: str, run: McpRun) -> None:
        if self._llm is None:
            raise RuntimeError("mcp-agent talk is not started")
        text = await self._llm.generate_str(prompt)
        if text:
            run._emit(str(text))

    async def _stream_openai(self, prompt: str, run: McpRun) -> None:
        from openai import AsyncOpenAI

        spec = talk_llm()
        messages: list[dict] = [
            {"role": "system", "content": TALK_INSTRUCTION},
            *self._history,
            {"role": "user", "content": prompt},
        ]
        client_kw: dict = {"api_key": spec["api_key"]}
        if spec["base_url"]:
            client_kw["base_url"] = spec["base_url"]
        model = spec["model"] or "openai/gpt-4o-mini"
        async with AsyncOpenAI(**client_kw) as client:
            for _ in range(5):
                if run._cancelled:
                    return
                acc: list[str] = []
                tools_acc: dict[int, dict[str, str]] = {}
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=[_WRITE_SPEC_TOOL],
                    stream=True,
                    max_tokens=1024,
                )
                async for ev in stream:
                    if run._cancelled:
                        return
                    if not ev.choices:
                        continue
                    delta = ev.choices[0].delta
                    if delta.content:
                        acc.append(delta.content)
                        run._emit(delta.content)
                    for tc in delta.tool_calls or ():
                        idx = int(tc.index or 0)
                        slot = tools_acc.setdefault(
                            idx, {"id": "", "name": "", "args": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        fn = tc.function
                        if fn is not None:
                            if fn.name:
                                slot["name"] += fn.name
                            if fn.arguments:
                                slot["args"] += fn.arguments
                if run._cancelled:
                    return
                if not tools_acc:
                    text = "".join(acc)
                    self._history.append({"role": "user", "content": prompt})
                    self._history.append({"role": "assistant", "content": text})
                    self._history = self._history[-20:]
                    return
                tool_calls = []
                for slot in tools_acc.values():
                    tool_calls.append(
                        {
                            "id": slot["id"],
                            "type": "function",
                            "function": {
                                "name": slot["name"],
                                "arguments": slot["args"],
                            },
                        }
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(acc) or None,
                        "tool_calls": tool_calls,
                    }
                )
                for slot in tools_acc.values():
                    name = slot["name"]
                    if "spec" in name:
                        try:
                            arg = json.loads(slot["args"] or "{}")
                        except json.JSONDecodeError:
                            arg = {"text": slot["args"]}
                        result = self._write_change_spec(
                            str(arg.get("text") or arg.get("instruction") or "")
                        )
                    else:
                        result = "unknown tool"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": slot["id"],
                            "content": result,
                        }
                    )

    def send(self, prompt: str) -> McpRun:
        if self._loop.is_closed() or not self._thread.is_alive():
            raise RuntimeError("mcp-agent talk is not started")
        run = McpRun()
        run._fut = asyncio.run_coroutine_threadsafe(
            self._talk_once(prompt, run), self._loop
        )
        return run

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
                fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
                try:
                    fut.result(timeout=8)
                except Exception:
                    pass
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
            elif not self._loop.is_closed():
                self._loop.run_until_complete(_shutdown())
        except Exception:
            pass
        finally:
            self._llm = None
            if not self._loop.is_closed():
                self._loop.close()
