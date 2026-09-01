# voice-cursor

Terminal voice loop on Windows. You talk to **mcp-agent**; Cursor CLI (`agent -p`) runs only when you say **apply**.

```text
mic or stdin → mcp-agent (talk) → print + Windows SAPI
                 ↘ say "apply" → `.voice-cursor/request.md` → Cursor CLI (`agent -p`)
```

This is not a GUI. It does not drive the Cursor IDE with Windows-MCP, and it does not use the Python `cursor_sdk.Agent.create` cloud path. Talk uses lastmile-ai [mcp-agent](https://docs.mcp-agent.com/get-started/welcome) (`MCPApp` + `Agent`) locally — not mcp-c / Temporal.

## Install

Python 3.11+, a microphone, the Cursor CLI (`agent`), and a talk LLM key.

```powershell
python -m pip install -e ".[dev,voice,talk]"
agent login
agent status
```

Put the OpenRouter key once in `%USERPROFILE%\.voice-cursor\.env` (the global installer copies your repo `.env` there). That key is used from every project. A `.env` in `--cwd` still wins if present.

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

See `.env.example`. Do not commit keys. Direct `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` still work. `agent login` uses your Cursor account. You can also set `CURSOR_API_KEY` or put that key in `%USERPROFILE%\.cursor\api-key`.

Windows install for the CLI if `agent` is missing:

```powershell
irm 'https://cursor.com/install?win32=true' | iex
```

## Check that it can hear you

This opens the real microphone, lists input devices, and transcribes **one** sentence:

```powershell
python -m voice_cursor listen-test
```

Or as a pytest (run this file alone so it is not skipped):

```powershell
python -m pytest tests/test_microphone.py -s
```

Say something like `Hey Cursor, microphone test`, then pause. The command prints `heard: ...` and exits 0. If the default input device is wrong or it hears nothing, it fails instead of passing silently.

The full suite skips that hardware test:

```powershell
python -m pytest -q
```

Force it inside the full suite with `--run-mic` or `$env:VOICE_CURSOR_REAL_MIC = "1"`.

## Use from anywhere

The command talks and, on apply, edits **whatever folder you point it at**, not this repo. Either `cd` into a project first, or pass `--cwd`.

Put `voice-cursor` on your PATH once (writes `%USERPROFILE%\.local\bin\voice-cursor.cmd`):

```powershell
cd C:\Users\nosre\desarrollos\vibe-coder-maximus
powershell -File scripts\install-global.ps1
```

Open a **new** terminal, then from any directory:

```powershell
cd C:\path\to\your\project
voice-cursor start --wake-word "hey cursor"
```

The wrapper always runs this repo's venv. Talk keys come from `%USERPROFILE%\.voice-cursor\.env`, not from each project. `--cwd` (default: the folder you are in) is only the workspace Cursor may edit on apply.

Or stay where you are and name the project:

```powershell
voice-cursor start --cwd C:\path\to\your\project --wake-word "hey cursor"
voice-cursor start --text --cwd C:\path\to\your\project
voice-cursor listen-test
```

`--cwd` is the folder Cursor may edit on apply. Talk turns do not spawn `agent -p`. Apply turns resume the same Cursor CLI session (`--resume`).

## Run a session (from this repo)

Typed fallback:

```powershell
python -m voice_cursor start --text
```

Voice:

```powershell
python -m voice_cursor start
python -m voice_cursor start --wake-word "hey cursor"
```

Work in another folder:

```powershell
python -m voice_cursor start --cwd C:\path\to\project
```

Talk replies come from mcp-agent. Cursor CLI runs only after `apply`. Replies are printed and spoken with Windows SAPI.

### Models (three different systems)

Voice-to-text is **not** Cursor. It is [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally:

| Piece | Default | Override |
| --- | --- | --- |
| Speech-to-text | Whisper **`base.en`**, CPU, int8 | `$env:VOICE_CURSOR_STT_MODEL = "small.en"` (or `tiny.en`, `medium.en`) |
| Talk | mcp-agent via OpenRouter (OpenAI-compatible) | `.env` `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`; or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| Coding (apply only) | Cursor CLI default model for your account | `agent` / Cursor settings |
| Text-to-speech | Windows SAPI (`System.Speech`) | none |

`tiny.en` is faster and sloppier; `small.en` is slower and clearer. Cache: `%USERPROFILE%\.voice-cursor\whisper`.

The session prints a live `you> …` line in the terminal while you speak. After you pause: `talk> (working...)` for conversation, or `cursor> (working...)` after apply.

Dry run (no mcp-agent, no Cursor, no mic):

```powershell
python -m voice_cursor start --fake --text
```

## In-session commands

| Input | Action |
| --- | --- |
| `stop listening`, `goodbye`, `exit`, `quit` | End the session |
| `apply`, `apply that`, `make the change`, `do it`, `go ahead`, `implement it` | Write/use `.voice-cursor/request.md`, one Cursor CLI call |
| `apply rename foo to bar` | Write that instruction into the spec, then Cursor CLI |
| `stop` while a run is active | Cancel the current run |
| `cancel`, `never mind` | Cancel the current run |
| `be quiet`, `silence` | Stop speech output |
| anything else | Talk (mcp-agent). Never `agent -p` |
| Ctrl+C | End the session |
