from pathlib import Path

from voice_cursor.spec import read_spec, spec_file, write_spec


def test_write_and_read_roundtrip(tmp_path: Path):
    path = write_spec(tmp_path, "  rename foo to bar  ")
    assert path == spec_file(tmp_path)
    assert path.name == "request.md"
    assert path.parent.name == ".voice-cursor"
    assert read_spec(tmp_path) == "rename foo to bar"


def test_read_missing_is_empty(tmp_path: Path):
    assert read_spec(tmp_path) == ""


def test_clear_spec_removes_file(tmp_path: Path):
    from voice_cursor.spec import clear_spec

    write_spec(tmp_path, "add a login endpoint")
    assert clear_spec(tmp_path) is True
    assert read_spec(tmp_path) == ""
    assert clear_spec(tmp_path) is False


def test_spec_stays_under_root(tmp_path: Path):
    path = spec_file(tmp_path)
    assert path.is_relative_to(tmp_path.resolve())
