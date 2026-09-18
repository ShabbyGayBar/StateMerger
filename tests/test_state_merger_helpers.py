import pytest

from vic3_state_merger.state_merger import (
    _build_keyword_pattern,
    _clear_output_dir,
    _iter_txt_files,
    _keyword_remove,
    _keyword_replace,
    _prefix_replace,
    _process_keyword_directory,
    _write_text_file,
)

pytestmark = pytest.mark.unit


def test_prefix_replace_and_helpers(tmp_path):
    text = "A = { }\n  B = { }\n# C = {}\n@x = 1\nREPLACE:D = {}\n"
    out = _prefix_replace(text)
    assert "REPLACE:A =" in out and "REPLACE:D" in out and "REPLACE:B" not in out
    p = tmp_path / "nested" / "x.txt"
    _write_text_file(p, "ok")
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    _clear_output_dir(tmp_path / "clear")
    assert (tmp_path / "clear").exists()


def test_keyword_context_and_empty_pattern():
    lookup, pattern = _build_keyword_pattern(
        {"STATE_LONG": ["STATE_X"], "S": ["STATE"]}
    )
    assert lookup["STATE_X"] == "STATE_LONG" and pattern is not None
    assert _build_keyword_pattern({}) == ({}, None)
    result = pattern.sub(
        lambda m: _keyword_replace(m, lookup, "STATE_X STATE_X_ANJOU"),
        "STATE_X STATE_X_ANJOU",
    )
    assert result == "STATE_LONG STATE_X_ANJOU"
    lookup, pattern = _build_keyword_pattern({"A": ["B"]})
    assert pattern.sub(lambda m: _keyword_remove(m, lookup, "B"), "B") == ""


def test_iter_and_process_keyword_directory(tmp_path):
    base = tmp_path / "base"
    mod = tmp_path / "mod"
    base.mkdir()
    (base / "a.txt").write_text("STATE_B = { }\n", encoding="utf-8")
    (base / "b.txt").write_text("none", encoding="utf-8")
    (base / "ignore.dat").write_text("STATE_B", encoding="utf-8")
    assert {x[0] for x in _iter_txt_files(base)} == {"a.txt", "b.txt"}
    lookup, pattern = _build_keyword_pattern({"STATE_A": ["STATE_B"]})
    transform = lambda text, lookup, pattern: pattern.sub(
        lambda m: _keyword_replace(m, lookup, text), text
    )
    _process_keyword_directory(str(base), str(mod), lookup, pattern, transform)
    assert "STATE_A" in (mod / "a.txt").read_text(encoding="utf-8-sig")
    _process_keyword_directory(
        str(base), str(mod), lookup, pattern, transform, aggregate=True
    )
    assert "REPLACE:STATE_A" in (mod / "state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
