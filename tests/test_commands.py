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


def test_apply_whisper_near_misses():
    for heard in ("applied", "applying", "Apply.", "go a head"):
        intent, extra = classify(heard)
        assert intent is Intent.APPLY, heard
        assert extra == ""


def test_apply_does_not_steal_reply_or_supply():
    assert classify("reply with a summary")[0] is Intent.PROMPT
    assert classify("supply a login form")[0] is Intent.PROMPT


def test_stop_listening_fuzzy():
    assert classify("stop listening!")[0] is Intent.STOP_SESSION
    assert classify("stopped listening")[0] is Intent.STOP_SESSION


def test_apply_exact_phrases():
    for heard in (
        "apply",
        "apply that",
        "make the change",
        "do it",
        "go ahead",
        "implement it",
    ):
        intent, extra = classify(heard)
        assert intent is Intent.APPLY, heard
        assert extra == ""


def test_apply_with_trailing_instruction():
    intent, extra = classify("apply rename foo to bar")
    assert intent is Intent.APPLY
    assert extra == "rename foo to bar"


def test_wake_word_then_apply():
    intent, extra = classify("hey cursor apply that", wake_word="hey cursor")
    assert intent is Intent.APPLY
    assert extra == ""


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


def test_help_status_repeat_clear():
    assert classify("help")[0] is Intent.HELP
    assert classify("what can I say")[0] is Intent.HELP
    assert classify("commands")[0] is Intent.HELP
    assert classify("status")[0] is Intent.STATUS
    assert classify("what's the plan")[0] is Intent.STATUS
    assert classify("repeat")[0] is Intent.REPEAT
    assert classify("say that again")[0] is Intent.REPEAT
    assert classify("forget that")[0] is Intent.CLEAR
    assert classify("scratch that")[0] is Intent.CLEAR


def test_scratch_that_cancels_when_running():
    assert classify("scratch that", run_active=True)[0] is Intent.CANCEL_RUN
    assert classify("forget that", run_active=True)[0] is Intent.CANCEL_RUN


def test_help_me_write_is_still_a_prompt():
    assert classify("help me write a test")[0] is Intent.PROMPT


def test_backchannel_exact_only():
    for heard in ("yeah", "yes", "ok", "okay", "uh-huh", "got it", "sure"):
        assert classify(heard)[0] is Intent.BACKCHANNEL, heard
    assert classify("yes add auth")[0] is Intent.PROMPT
    assert classify("okay apply")[0] is Intent.PROMPT
