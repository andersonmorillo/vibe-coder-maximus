from voice_cursor.speakable import speakable


def test_strips_fenced_code():
    text = "Created the endpoint.\n```python\nprint(1)\n```\nDone."
    out = speakable(text)
    assert "print" not in out
    assert "Created the endpoint." in out
    assert "Done." in out


def test_keeps_short_inline_code():
    assert speakable("Use `POST` on login.") == "Use POST on login."


def test_empty():
    assert speakable("") == ""
    assert speakable("   ") == ""
