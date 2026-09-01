from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from voice_cursor.fake import FakeAgent
from voice_cursor.io import StdinListener, TeeSpeaker
from voice_cursor.loop import run_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-cursor",
        description=(
            "Voice loop around the Cursor CLI in this folder. "
            "Uses `agent -p`, not the Python SDK and not Windows-MCP."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "listen-test",
        help="open the microphone, transcribe one sentence, exit",
    )
    start = sub.add_parser("start", help="start a session")
    start.add_argument("--text", action="store_true", help="type instead of the mic")
    start.add_argument("--cwd", default=".", help="local workspace the agent may edit")
    start.add_argument("--wake-word", default="", help='optional prefix, e.g. "hey cursor"')
    start.add_argument(
        "--fake",
        action="store_true",
        help="canned replies; no Cursor CLI (dry run)",
    )
    start.add_argument("--no-tts", action="store_true", help="print replies, do not speak")
    start.add_argument(
        "--agent-bin",
        default="",
        help="path to the Cursor CLI `agent` binary (else PATH / ~/.local/bin)",
    )
    args = parser.parse_args(argv)
    if args.cmd == "listen-test":
        return run_listen_test()
    if args.cmd != "start":
        parser.error("unknown command")
    return start_session(args)


def run_listen_test() -> int:
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
        heard = listen_once()
    except Exception as exc:
        print(f"voice-cursor: listen-test failed ({exc})", file=sys.stderr)
        return 1
    print(f"heard: {heard}", flush=True)
    return 0


def start_session(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        print(f"voice-cursor: cwd is not a directory: {cwd}", file=sys.stderr)
        return 1
    os.chdir(cwd)

    use_text = bool(args.text or args.fake)
    voice = None
    if not args.no_tts:
        from voice_cursor.tts import SapiSpeaker

        voice = SapiSpeaker()
    speaker = TeeSpeaker(voice)

    if args.fake:
        agent = FakeAgent()
        listener = StdinListener()
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
        if use_text:
            listener = StdinListener()
        else:
            try:
                from voice_cursor.stt import WhisperListener

                listener = WhisperListener(wake_word=args.wake_word)
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

    print(
        f"voice-cursor: Cursor CLI in {cwd}  "
        "(files stay on this PC; Ctrl+C or 'stop listening' to end)",
        flush=True,
    )
    try:
        run_session(
            listener=listener,
            speaker=speaker,
            agent=agent,
            wake_word=args.wake_word,
        )
    except KeyboardInterrupt:
        print("\nvoice-cursor: stopped")
    return 0
