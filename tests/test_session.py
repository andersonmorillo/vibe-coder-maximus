from voice_cursor.session import Phase, Session


def test_starts_listening():
    s = Session()
    assert s.phase is Phase.LISTENING
    assert s.is_open
    assert not s.run_active


def test_run_then_speak_then_listen():
    s = Session()
    s.begin_run()
    assert s.run_active
    s.begin_speak()
    assert s.phase is Phase.SPEAKING
    s.end_turn()
    assert s.phase is Phase.LISTENING
    assert not s.run_active


def test_stop_is_terminal():
    s = Session()
    s.begin_run()
    s.stop()
    assert s.phase is Phase.STOPPING
    assert not s.is_open
    s.begin_run()
    s.end_turn()
    assert s.phase is Phase.STOPPING
