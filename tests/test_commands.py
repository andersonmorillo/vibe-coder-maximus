from voice_cursor.commands import Intent, classify


def test_stop_listening_ends_session():
    intent, payload = classify("Stop listening")
    assert intent is Intent.STOP_SESSION
    assert payload == "Stop listening"


def test_stop_while_idle_ends_session():
    intent, _ = classify("stop", run_active=False)
    assert intent is Intent.STOP_SESSION


def test_stop_while_running_cancels_run():
    intent, _ = classify("stop", run_active=True)
    assert intent is Intent.CANCEL_RUN


def test_cancel_only_when_running():
    assert classify("cancel", run_active=False)[0] is Intent.PROMPT
    assert classify("never mind", run_active=True)[0] is Intent.CANCEL_RUN


def test_quiet():
    assert classify("be quiet")[0] is Intent.QUIET


def test_prompt_passthrough():
    intent, payload = classify("create a login endpoint")
    assert intent is Intent.PROMPT
    assert payload == "create a login endpoint"


def test_wake_word_required_then_stripped():
    intent, payload = classify(
        "hey cursor create a login endpoint",
        wake_word="hey cursor",
    )
    assert intent is Intent.PROMPT
    assert payload.lower() == "create a login endpoint"


def test_missing_wake_word_is_ignored():
    intent, _ = classify("create a login endpoint", wake_word="hey cursor")
    assert intent is Intent.IGNORE


def test_blank_is_ignored():
    assert classify("   ")[0] is Intent.IGNORE
