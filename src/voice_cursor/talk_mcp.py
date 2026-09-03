"""Talk port backed by lastmile-ai mcp-agent (local MCPApp, not mcp-c).

Sources:
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/agents.md
https://docs.mcp-agent.com/mcp-agent-sdk/core-components/mcpapp.md
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import threading
from queue import Empty, Queue
from typing import Iterator

from voice_cursor.envfile import apply_talk_credentials, load_cwd_dotenv, talk_llm
from voice_cursor.spec import write_spec

def talk_instruction(handoff_target: str = "Firstmate") -> str:
    return (
        "You are a voice coding assistant. Keep replies to 2-4 short spoken "
        "sentences. You may inspect repository files with read-only filesystem "
        "tools, but never edit source files. The only write operation available "
        "is write_change_spec, which records a handoff request. No code fences. "
        "If the user wants a code change, call "
        f"write_change_spec with a clear instruction for {handoff_target}. "
        "Do not claim you edited the repo. The user must say apply to hand it "
        f"to {handoff_target}."
    )


TALK_INSTRUCTION = talk_instruction()

_READ_ONLY_FILESYSTEM_TOOLS = frozenset(
    {
        "read_text_file",
        "read_media_file",
        "read_multiple_files",
        "list_directory",
        "list_directory_with_sizes",
        "directory_tree",
        "search_files",
        "get_file_info",
        "list_allowed_directories",
    }
)


def _filesystem_tool_allowed(name: str) -> bool:
    return name == "write_change_spec" or (
        name.startswith("filesystem_")
        and name.removeprefix("filesystem_") in _READ_ONLY_FILESYSTEM_TOOLS
    )


def _mcp_result_text(result) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
            continue
        model_dump = getattr(item, "model_dump", None)
        if model_dump is not None:
            parts.append(json.dumps(model_dump(), default=str))
        else:
            parts.append(str(item))
    text = "\n".join(parts) or "Tool returned no content."
    return f"Error: {text}" if getattr(result, "isError", False) else text


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

    def __init__(self, cwd: str, handoff_target: str = "Firstmate") -> None:
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
        self._handoff_target = handoff_target
        self._instruction = talk_instruction(handoff_target)
        self._history: list[dict] = []
        self._loop = asyncio.new_event_loop()
        self._app_cm = None
        self._agent_cm = None
        self._agent = None
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
        """Save a code-change request for the selected coding engine."""
        write_spec(self._cwd, text)
        return (
            "Spec saved. Tell the user to say apply when they want "
            f"{self._handoff_target} to handle the project."
        )

    async def _boot(self, MCPApp, Agent) -> None:
        from mcp_agent.config import (
            LoggerSettings,
            MCPServerSettings,
            MCPSettings,
            OpenAISettings,
            Settings,
        )

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
        repo = Path(self._cwd).resolve()
        root_uri = repo.as_uri()
        if os.name == "nt":
            filesystem_command = "cmd"
            filesystem_args = [
                "/c",
                "npx",
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(repo),
            ]
        else:
            filesystem_command = "npx"
            filesystem_args = [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(repo),
            ]
        kwargs["mcp"] = MCPSettings(
            servers={
                "filesystem": MCPServerSettings(
                    name="repository-filesystem",
                    description="Read-only access to the current repository.",
                    command=filesystem_command,
                    args=filesystem_args,
                    cwd=str(repo),
                    roots=[
                        {
                            "uri": root_uri,
                            "name": "repository",
                            "server_uri_alias": root_uri,
                        }
                    ],
                    allowed_tools=set(_READ_ONLY_FILESYSTEM_TOOLS),
                )
            }
        )
        settings = Settings(_env_file=None, **kwargs)
        app = MCPApp(name="voice-cursor-talk", settings=settings)
        self._app_cm = app.run()
        running = await self._app_cm.__aenter__()

        class ReadOnlyAgent(Agent):
            async def call_tool(self, name: str, arguments: dict | None = None):
                if not _filesystem_tool_allowed(name):
                    raise PermissionError(
                        f"Filesystem tool '{name}' is disabled for the talk agent."
                    )
                return await super().call_tool(name, arguments)

        agent = ReadOnlyAgent(
            name="talk",
            instruction=self._instruction,
            functions=[self._write_change_spec],
            server_names=["filesystem"],
            context=running.context,
        )
        self._agent = agent
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

        if self._agent is None:
            raise RuntimeError("mcp-agent talk is not started")
        spec = talk_llm()
        messages: list[dict] = [
            {"role": "system", "content": self._instruction},
            *self._history,
            {"role": "user", "content": prompt},
        ]
        client_kw: dict = {"api_key": spec["api_key"]}
        if spec["base_url"]:
            client_kw["base_url"] = spec["base_url"]
        model = spec["model"] or "openai/gpt-4o-mini"
        tool_result = await self._agent.list_tools()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in tool_result.tools
        ]
        tool_names = {tool["function"]["name"] for tool in tools}
        async with AsyncOpenAI(**client_kw) as client:
            for _ in range(5):
                if run._cancelled:
                    return
                acc: list[str] = []
                tools_acc: dict[int, dict[str, str]] = {}
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools or None,
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
                    if name not in tool_names or not _filesystem_tool_allowed(name):
                        result = f"Tool '{name}' is not available."
                    else:
                        try:
                            tool_args = json.loads(slot["args"] or "{}")
                        except json.JSONDecodeError:
                            result = f"Invalid JSON arguments for tool '{name}'."
                        else:
                            if not isinstance(tool_args, dict):
                                result = f"Tool '{name}' requires an object of arguments."
                            else:
                                mcp_result = await self._agent.call_tool(name, tool_args)
                                result = _mcp_result_text(mcp_result)
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
