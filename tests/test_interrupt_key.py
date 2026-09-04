from voice_cursor.interrupt_key import InterruptKey


def test_interrupt_key_disabled_without_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    key = InterruptKey()
    assert key.poll() is False
    key.close()


def test_interrupt_key_polls_once(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    key = InterruptKey()
    key._pressed.set()
    assert key.poll() is True
    assert key.poll() is False
    key.close()
