# voice-cursor

Terminal voice loop. You talk to **mcp-agent**; **apply** edits the project
you launched from (Cursor CLI by default).

```text
mic or stdin → mcp-agent (talk) → print + Windows SAPI
                 ↘ say "apply" → Cursor CLI in the current project
```

Install once, then run it from any repo. This is not a GUI, not Windows-MCP,
and not the Python `cursor_sdk.Agent.create` cloud path. Talk uses lastmile-ai
[mcp-agent](https://docs.mcp-agent.com/get-started/welcome) (`MCPApp` + `Agent`)
locally — not mcp-c / Temporal.

## Global install (any project)

One-time setup from this repo. Requires Node 18+ and Python 3.11–3.13
(Python 3.12 is recommended because WhisperX does not support 3.14 yet).
Installs to `~/.local` so you do not need sudo:

```sh
cd /path/to/vibe-coder-maximus
bash scripts/install-global.sh
```

Equivalent:

```sh
npm install -g --prefix "$HOME/.local" .
export PATH="$HOME/.local/bin:$PATH"
```

That puts `voice-cursor` on your PATH and installs the Python talk and
microphone runtimes into this package's `.venv`. Add your key once:

```sh
mkdir -p ~/.voice-cursor
cp .env.example ~/.voice-cursor/.env
nano ~/.voice-cursor/.env   # set OPENROUTER_API_KEY
```

Authenticate the Cursor CLI once (`cursor-agent login` on WSL, `agent login`
on native Windows).

Then, from **any** project directory:

```sh
cd /path/to/the/other/project
voice-cursor --text --no-tts
```

or:

```sh
npx voice-cursor --text --no-tts
```

Inside this repo only, `npm run agent -- --text --no-tts` is the same command.
You do not add a `package.json` script to the other project.

`--cwd` defaults to the directory you ran the command in. **Apply** uses
Firstmate by default (queues the change through its isolated workflow).
Pass `--engine cursor` when you want the legacy direct Cursor CLI path instead.

Use `--text --no-tts` for a text-only session. The global installer includes
microphone support for the normal command without those flags.

On native Windows, `scripts/install-global.ps1` is the older PATH shim; npm
is the supported global launcher.

## Publish to npm

The package name `voice-cursor` is currently unclaimed. Before publishing:

```sh
npm login
npm test
npm publish --access public
```

Afterward, users can install it globally with `npm install -g voice-cursor` or
run it with `npx voice-cursor`. A published install cannot guess an unrelated
Firstmate checkout; set `VOICE_CURSOR_FIRSTMATE_ROOT` once in
`~/.voice-cursor/.env` when using the Firstmate engine.

## Firstmate engine from WSL

The global installer automatically records the Firstmate checkout when it is
run from inside that checkout, including this layout:

```text
/path/to/firstmate/
├── AGENTS.md
└── vibe-coder-maximus/
```

From this repository:

```sh
sudo apt update
sudo apt install -y python3-pip python3-venv tmux nodejs npm
cd /path/to/firstmate/vibe-coder-maximus
bash scripts/install-global.sh
```

The installer stores `VOICE_CURSOR_FIRSTMATE_ROOT` in
`~/.voice-cursor/.env`. It does not overwrite a root you already configured.
Then, from any registered project:

```sh
cd /path/to/project
voice-cursor --text --no-tts
```

The project must already be registered with Firstmate for apply to work.

If the package was installed from npm rather than from inside a Firstmate
checkout, set the root once in `~/.voice-cursor/.env`:

```sh
VOICE_CURSOR_FIRSTMATE_ROOT=/path/to/firstmate
```

At the voice-cursor prompt, describe the change, then type `apply`.

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

The global `voice-cursor` / `npx voice-cursor` command is the easy path for
other projects: it defaults to `--engine firstmate` and `--cwd` of the current
directory, so **apply** hands work to Firstmate.

`VOICE_CURSOR_FIRSTMATE_ROOT` can provide the checkout instead of
`--firstmate-root` when Firstmate is not auto-discovered.
`VOICE_CURSOR_FIRSTMATE_HOME` or `FM_HOME` can select a separate operational
home.
`--firstmate-session` overrides the generated tmux session name.
`--primary-model` passes a model to the Cursor primary.
A Firstmate apply still requires that project to be registered with Firstmate;
that path queues the request with `bin/fm-inbox.sh note` and does not edit
the launch folder directly.

Talk replies come from mcp-agent, which can inspect the target repository through
read-only filesystem MCP tools.
Source files are not modified during talk turns.

### Models (three different systems)

Voice-to-text is **not** Cursor. Listen uses [WhisperX](https://github.com/m-bain/whisperX) on CUDA. [s1-mini](https://huggingface.co/superwhisper/s1-mini) was not selected because it is a transcript cleaner, not a microphone model.

| Piece | Default | Override |
| --- | --- | --- |
| Speech-to-text | Whisper **`base.en`**, **CUDA float16 when the CUDA runtime is available**, else CPU int8 | `$env:VOICE_CURSOR_STT_DEVICE = "cpu"` or `"cuda"`; `$env:VOICE_CURSOR_STT_MODEL = "small.en"` |
| Speech gate | adaptive vs mic noise (not a fixed 0.012 RMS) | `$env:VOICE_CURSOR_STT_THRESHOLD = "0.012"` to force an absolute gate |
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
| `help`, `what can I say`, `commands` | Speak the command map |
| `status`, `what's the plan`, `read the spec` | Speak the pending change spec |
| `repeat`, `say that again` | Re-speak the last reply |
| `forget that`, `scratch that`, `clear the plan` | Drop the local spec (or cancel if a run is active) |
| `yeah`, `ok`, `uh-huh`, `got it` | Backchannel: ignored, does not talk or abort a run |
| `apply`, `applied`, `apply that`, `make the change`, `do it`, `go ahead`, `implement it` | Print/speak the spec, then queue it for Firstmate |
| `apply rename foo to bar` | Write that instruction into the spec, then queue it for Firstmate |
| `stop` while a run is active | Cancel the current run |
| `stop` while I'm speaking | Stop speech and wait for your next sentence |
| `cancel`, `never mind` | Cancel the current run |
| `be quiet`, `silence` | Stop speech output |
| Enter (keyboard, mic mode) | Stop speech and wait for your next sentence |
| anything else | Talk (mcp-agent). Never edit the project directly |
| Ctrl+C | End the session |

See [docs/interaction-plan.md](docs/interaction-plan.md) for the research mapping and later ideas.
