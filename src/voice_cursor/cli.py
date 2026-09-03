from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from voice_cursor.firstmate import FirstmateAgent
from voice_cursor.io import StdinListener, TeeSpeaker
from voice_cursor.loop import run_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-cursor",
        description=(
            "Voice loop: mcp-agent for talk, Firstmate handles apply by default. "
            "Not the Python SDK and not Windows-MCP."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    listen = sub.add_parser(
        "listen-test",
        help="open the microphone, transcribe one sentence, exit",
    )
    listen.add_argument(
        "--device",
        type=int,
        default=None,
        help="microphone device index (see printed list)",
    )
    doctor = sub.add_parser(
        "doctor",
        help="check talk key, CUDA Whisper, mic, and coding engine",
    )
    doctor.add_argument("--cwd", default=".", help="workspace to load .env from")
    start = sub.add_parser("start", help="start a session")
    start.add_argument("--text", action="store_true", help="type instead of the mic")
    start.add_argument("--cwd", default=".", help="local workspace the agent may edit")
    start.add_argument(
        "--engine",
        choices=("firstmate", "cursor"),
        default="firstmate",
        help="coding engine (default: firstmate)",
    )
    start.add_argument(
        "--firstmate-root",
        default="",
        help="Firstmate checkout to launch (or VOICE_CURSOR_FIRSTMATE_ROOT)",
    )
    start.add_argument(
        "--firstmate-home",
        default="",
        help="Firstmate operational home (or VOICE_CURSOR_FIRSTMATE_HOME/FM_HOME)",
    )
    start.add_argument(
        "--firstmate-session",
        default="",
        help="tmux session name for the Firstmate primary",
    )
    start.add_argument(
        "--primary-model",
        default="",
        help="Cursor model for the Firstmate primary",
    )
    start.add_argument("--wake-word", default="", help='optional prefix, e.g. "hey cursor"')
    start.add_argument(
        "--device",
        type=int,
        default=None,
        help="microphone device index (see listen-test / doctor)",
    )
    start.add_argument(
        "--fake",
        action="store_true",
        help="canned replies; no mcp-agent and no Cursor CLI (dry run)",
    )
    start.add_argument("--no-tts", action="store_true", help="print replies, do not speak")
    start.add_argument(
        "--agent-bin",
        default="",
        help="path to the Cursor CLI used by the selected engine",
    )
    args = parser.parse_args(argv)
    if args.cmd == "listen-test":
        return run_listen_test(device=args.device)
    if args.cmd == "doctor":
        from voice_cursor.doctor import run_doctor

        return run_doctor(args.cwd)
    if args.cmd != "start":
        parser.error("unknown command")
    return start_session(args)


def run_listen_test(*, device: int | None = None) -> int:
    try:
        from voice_cursor.stt import listen_once
    except Exception as exc:
        print(
            f"voice-cursor: mic STT unavailable ({exc}). "
            'Install extras: pip install -e ".[voice]"',
            file=sys.stderr,
        )
        return 1
    try:
        heard = listen_once(device=device)
    except Exception as exc:
        print(f"voice-cursor: listen-test failed ({exc})", file=sys.stderr)
        return 1
    print(f"heard: {heard}", flush=True)
    return 0


def _boot_status(cwd: Path, *, fake: bool, engine: str) -> None:
    from voice_cursor.envfile import talk_status_line
    from voice_cursor.stt import runtime_summary

    extra = "fake" if fake else runtime_summary()
    print(f"voice-cursor: {talk_status_line()}  stt: {extra}", flush=True)
    if fake:
        apply_target = "dry run"
    elif engine == "firstmate":
        apply_target = "Firstmate inbox"
    else:
        apply_target = "Cursor CLI"
    print(
        f"voice-cursor: session in {cwd}  "
        f"(talk: mcp-agent; apply: {apply_target}; "
        "Ctrl+C or 'stop listening' to end)",
        flush=True,
    )


def start_session(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        print(f"voice-cursor: cwd is not a directory: {cwd}", file=sys.stderr)
        return 1
    os.chdir(cwd)
    from voice_cursor.envfile import load_cwd_dotenv

    load_cwd_dotenv(cwd)

    use_text = bool(args.text or args.fake)
    voice = None
    if not args.no_tts:
        from voice_cursor.tts import SapiSpeaker

        voice = SapiSpeaker()
    speaker = TeeSpeaker(voice)

    engine = getattr(args, "engine", "firstmate")
    apply_target = "Firstmate" if engine == "firstmate" else "Cursor CLI"
    if args.fake:
        from voice_cursor.fake import FakeAgent, FakeTalkAgent

        agent = FakeAgent()
        talk = FakeTalkAgent(spec_root=str(cwd))
        listener = StdinListener()
    elif engine == "firstmate":
        try:
            agent = FirstmateAgent(
                cwd=str(cwd),
                firstmate_root=args.firstmate_root,
                firstmate_home=args.firstmate_home,
                session=args.firstmate_session,
                binary=args.agent_bin or None,
                model=args.primary_model or None,
            )
        except Exception as exc:
            print(
                f"voice-cursor: could not configure Firstmate ({exc})",
                file=sys.stderr,
            )
            return 1
        talk = None
    else:
        from voice_cursor.cursor_cli import (
            CursorCliAgent,
            cli_authenticated,
            find_agent_cli,
            install_hint,
            login_hint,
        )

        binary = args.agent_bin or find_agent_cli()
        if not binary:
            print(install_hint(), file=sys.stderr)
            return 1
        if not cli_authenticated(binary):
            print(login_hint(), file=sys.stderr)
            return 1
        try:
            agent = CursorCliAgent(cwd=str(cwd), binary=binary)
        except Exception as exc:
            print(f"voice-cursor: could not start Cursor CLI ({exc})", file=sys.stderr)
            return 1

    if not args.fake:
        if use_text:
            listener = StdinListener()
        else:
            try:
                from voice_cursor.stt import WhisperListener

                listener = WhisperListener(
                    wake_word=args.wake_word, device=args.device
                )
            except Exception as exc:
                print(
                    f"voice-cursor: mic STT unavailable ({exc}). "
                    'Install extras: pip install -e ".[voice]"  or use --text.',
                    file=sys.stderr,
                )
                agent.close()
                return 1
            print("voice-cursor: loading speech recognition...", flush=True)
            if not listener.wait_ready():
                detail = listener._error or "STT timed out"
                print(f"voice-cursor: {detail}. Use --text.", file=sys.stderr)
                listener.close()
                agent.close()
                return 1
            from voice_cursor.stt import describe_input_devices, runtime_summary

            print(
                f"voice-cursor: transcribing with {runtime_summary()} "
                f"(not a Cursor model; mcp-agent talks, {apply_target} handles apply)",
                flush=True,
            )
            print("Input devices:", flush=True)
            print(describe_input_devices(args.device), flush=True)
            print(
                "voice-cursor: listening — speak, then pause ~1s. "
                f"Talk is mcp-agent; say apply to use {apply_target}.",
                flush=True,
            )
        from voice_cursor.talk_mcp import McpTalkAgent

        try:
            talk = McpTalkAgent(
                cwd=str(cwd),
                handoff_target="Firstmate" if engine == "firstmate" else "Cursor",
            )
        except Exception as exc:
            print(f"voice-cursor: could not start mcp-agent talk ({exc})", file=sys.stderr)
            closer = getattr(listener, "close", None)
            if closer is not None:
                closer()
            agent.close()
            return 1

    if engine == "firstmate" and not args.fake:
        try:
            agent.start()
        except Exception as exc:
            print(
                f"voice-cursor: could not launch Firstmate ({exc})",
                file=sys.stderr,
            )
            closer = getattr(listener, "close", None)
            if closer is not None:
                closer()
            if talk is not None:
                talk.close()
            agent.close()
            return 1
        print(f"voice-cursor: {agent.startup_message}", flush=True)

    _boot_status(cwd, fake=bool(args.fake), engine=engine)
    try:
        run_session(
            listener=listener,
            speaker=speaker,
            agent=agent,
            talk=talk,
            spec_root=cwd,
            wake_word=args.wake_word,
        )
    except KeyboardInterrupt:
        print("\nvoice-cursor: stopped")
    return 0
