# voice-cursor

Terminal voice loop on Windows. You talk to **mcp-agent**; Firstmate handles the
project only when you say **apply**.

```text
mic or stdin → mcp-agent (talk) → print + Windows SAPI
                 ↘ say "apply" → `.voice-cursor/request.md` → Firstmate inbox
                                                        ↘ isolated worker
```

This is not a GUI. It does not drive the Cursor IDE with Windows-MCP, and it does not use the Python `cursor_sdk.Agent.create` cloud path. Talk uses lastmile-ai [mcp-agent](https://docs.mcp-agent.com/get-started/welcome) (`MCPApp` + `Agent`) locally — not mcp-c / Temporal.

## Quick start from WSL

Use this path when Firstmate is on WSL.
The voice frontend starts a trusted Cursor primary in tmux, and that primary runs Firstmate's `bin/fm-session-start.sh` setup hook automatically.

Clone the complete voice frontend from GitHub:

```sh
mkdir -p "$HOME/src"
git clone https://github.com/andersonmorillo/vibe-coder-maximus.git \
  "$HOME/src/vibe-coder-maximus"
cd "$HOME/src/vibe-coder-maximus"
```

If the folder is already cloned, just run:

```sh
cd "$HOME/src/vibe-coder-maximus"
git pull --ff-only
```

Set the local paths.
`FIRSTMATE_ROOT` must point to your Firstmate checkout.
`PROJECT_ROOT` is the project Firstmate will work on; for this example it is
the cloned voice frontend:

```sh
export VOICE_CURSOR_ROOT="$HOME/src/vibe-coder-maximus"
export FIRSTMATE_ROOT=/path/to/firstmate
export PROJECT_ROOT="$VOICE_CURSOR_ROOT"
```

Install the local prerequisites once:

```sh
sudo apt update
sudo apt install -y python3-pip python3-venv tmux nodejs npm
cd "$VOICE_CURSOR_ROOT"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[voice,talk]"
```

Create the talk configuration and add your key:

```sh
mkdir -p ~/.voice-cursor
cp .env.example ~/.voice-cursor/.env
nano ~/.voice-cursor/.env
```

Set `OPENROUTER_API_KEY` in that file.
Do not commit the file.

Authenticate the Cursor primary:

```sh
cursor-agent login
cursor-agent status
```

Run a text-only session first:

```sh
cd "$VOICE_CURSOR_ROOT"
. .venv/bin/activate
python -m voice_cursor start \
  --firstmate-root "$FIRSTMATE_ROOT" \
  --cwd "$PROJECT_ROOT" \
  --text \
  --no-tts
```

The command prints the tmux session to attach to.
The target project must be registered in the Firstmate home before applying work.
If Firstmate already has its own clone of the project, set `PROJECT_ROOT` to
that clone instead.
At the voice-cursor prompt, describe the change, then type `apply`.
Firstmate receives the request through its inbox and handles the project in its normal isolated workflow.

Test the installation without an API key, microphone, or Cursor session:

```sh
cd "$VOICE_CURSOR_ROOT"
. .venv/bin/activate
printf 'say hello\napply\nquit\n' | python -m voice_cursor start --fake --text --no-tts
```

## Native Windows notes

The Firstmate engine runs in WSL.
Native Windows can still run the legacy direct-Cursor mode with `--engine cursor`.
Install the Python extras in PowerShell:

```powershell
python -m pip install -e ".[dev,voice,talk]"
agent login
agent status
```

Put the OpenRouter key in `%USERPROFILE%\.voice-cursor\.env`.
See `.env.example`.
Do not commit keys.

Install the Cursor CLI if `agent` is missing:

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

## Configuration and alternatives

The quick-start command is the recommended Firstmate workflow.
`VOICE_CURSOR_FIRSTMATE_ROOT` can provide the checkout instead of
`--firstmate-root`.
`VOICE_CURSOR_FIRSTMATE_HOME` or `FM_HOME` can select a separate operational
home.
`--firstmate-session` overrides the generated tmux session name.
`--primary-model` passes a model to the Cursor primary.
The project must already be registered in the Firstmate home.
Apply turns enqueue the request with `bin/fm-inbox.sh note`.
The voice frontend does not edit the project directly.

For the old direct Cursor behavior, opt in explicitly:

```sh
python -m voice_cursor start --engine cursor --cwd /path/to/project
```

Talk replies come from mcp-agent, which can inspect the target repository through
read-only filesystem MCP tools.
Firstmate receives work only after `apply`.
Source files are not modified during talk turns.

### Models (three different systems)

Voice-to-text is **not** Cursor. It is [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally:

| Piece | Default | Override |
| --- | --- | --- |
| Speech-to-text | Whisper **`base.en`**, **CUDA float16 if a GPU is found**, else CPU int8 | `$env:VOICE_CURSOR_STT_DEVICE = "cpu"` or `"cuda"`; `$env:VOICE_CURSOR_STT_MODEL = "small.en"` |
| Microphone | system default | `--device N` or `$env:VOICE_CURSOR_MIC_DEVICE = "N"` (`voice-cursor doctor` lists indexes) |
| Talk | mcp-agent via OpenRouter (OpenAI-compatible) | `.env` `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`; or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| Coding (apply only) | Firstmate primary using Cursor CLI | `--primary-model` or Cursor settings |
| Text-to-speech | Windows SAPI (`System.Speech`) | none |

`tiny.en` is faster and sloppier; `small.en` is slower and clearer. Cache: `%USERPROFILE%\.voice-cursor\whisper`.

The session prints a live `you> …` line in the terminal while you speak. After
you pause: `talk> (working...)` for conversation, or `firstmate> (working...)`
after apply.

Dry run (no mcp-agent, no Cursor, no mic):

```powershell
python -m voice_cursor start --fake --text
```

## In-session commands

| Input | Action |
| --- | --- |
| `stop listening`, `goodbye`, `exit`, `quit` | End the session |
| `apply`, `applied`, `apply that`, `make the change`, `do it`, `go ahead`, `implement it` | Print/speak the spec, then queue it for Firstmate |
| `apply rename foo to bar` | Write that instruction into the spec, then queue it for Firstmate |
| `stop` while a run is active | Cancel the current run |
| `cancel`, `never mind` | Cancel the current run |
| `be quiet`, `silence` | Stop speech output |
| anything else | Talk (mcp-agent). Never edit the project directly |
| Ctrl+C | End the session |
