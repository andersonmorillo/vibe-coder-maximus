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


def test_spoken_preview_flattens_and_caps():
    from voice_cursor.speakable import spoken_preview

    assert spoken_preview("add a login") == "add a login"
    assert spoken_preview("a\n\nb") == "a b"
    long = "x" * 250
    out = spoken_preview(long, limit=10)
    assert out == "xxxxxxx..."
    assert len(out) == 10
