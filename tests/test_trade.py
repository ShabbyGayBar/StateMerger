import pytest

from vic3_state_merger.trade import Trade

pytestmark = pytest.mark.unit


def test_trade_format_and_merge(trade_data):
    t = Trade(trade_data)
    assert t["s:A"]["R"]["grain"]["add_exports"] == 2
    assert t["s:B"]["R"]["iron"]["add_exports"] == 0
    t.merge_states({"A": ["B"]})
    assert "s:B" not in t and t["s:A"]["R"]["grain"] == {
        "add_exports": 5,
        "add_imports": 5,
    }


def test_trade_serialization_omits_nonpositive():
    t = Trade(
        {"TRADE": {"s:A": {"R": {"grain": {"add_exports": 0, "add_imports": 2}}}}}
    )
    text = t.get_str("s:A")
    assert "add_exports" not in text and "add_imports = 2" in text
    assert t.get_str("missing") == ""


def test_trade_dump_bom(tmp_path, trade_data):
    p = tmp_path / "t.txt"
    Trade(trade_data).dump(p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
