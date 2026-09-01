from __future__ import annotations

import os


def pytest_addoption(parser):
    parser.addoption(
        "--run-mic",
        action="store_true",
        default=False,
        help="run the real microphone listen test even in the full suite",
    )


def pytest_collection_modifyitems(config, items):
    import pytest

    mic = [item for item in items if item.get_closest_marker("real_mic")]
    if not mic:
        return
    enabled = bool(os.environ.get("VOICE_CURSOR_REAL_MIC")) or bool(
        config.getoption("--run-mic")
    )
    only_mic = len(items) == len(mic)
    if enabled or only_mic:
        return
    skip = pytest.mark.skip(
        reason="real microphone; run tests/test_microphone.py -s or pass --run-mic"
    )
    for item in mic:
        item.add_marker(skip)
