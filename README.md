# voice-cursor

Terminal voice loop around the **Cursor CLI** on Windows. You speak (or type), Cursor works in this folder, then you hear the reply and can keep talking in the same conversation.

```text
mic or stdin → Cursor CLI (`agent -p`) → print + Windows SAPI → next turn
```

This is not a GUI. It does not drive the Cursor IDE with Windows-MCP, and it does not use the Python `cursor_sdk.Agent.create` cloud path.

## Install

Python 3.11+, a microphone, and the Cursor CLI (`agent`).

```powershell
python -m pip install -e ".[dev,voice]"
agent login
agent status
```

`agent login` uses your Cursor account. You can also set `CURSOR_API_KEY` or put the key in `%USERPROFILE%\.cursor\api-key`. Do not commit keys.

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

## Run a session

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

Follow-ups reuse the same Cursor CLI session (`--resume`). Replies are printed and spoken with Windows SAPI.

Dry run (no Cursor, no mic):

```powershell
python -m voice_cursor start --fake --text
```

## In-session commands

| Input | Action |
| --- | --- |
| `stop listening`, `goodbye`, `exit`, `quit` | End the session |
| `stop` while Cursor is working | Cancel the current run |
| `cancel`, `never mind` | Cancel the current run |
| `be quiet`, `silence` | Stop speech output |
| Ctrl+C | End the session |
