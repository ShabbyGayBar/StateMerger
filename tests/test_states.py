import pytest

from vic3_state_merger.states import States

pytestmark = pytest.mark.unit


def test_format_merge_and_serialization(states_data):
    s = States(states_data)
    assert s["s:A"]["create_state"][0]["owned_provinces"] == ["p1"]
    s.merge_states({"A": ["B"]})
    a = s["s:A"]
    assert "s:B" not in s and a["create_state"][0]["owned_provinces"] == [
        "p1",
        "p2",
        "p3",
    ]
    assert set(a["add_homeland"]) == {"cul_a", "cul_b"} and set(a["add_claim"]) == {
        "c:USA",
        "c:FRA",
    }
    assert "owned_provinces" in str(s)


@pytest.mark.xfail(
    strict=True, reason="States.merge_state indexes missing target add_homeland"
)
def test_merge_homeland_into_target_without_homeland():
    s = States(
        {
            "STATES": {
                "s:A": {"create_state": {"country": "c:A", "owned_provinces": "p1"}},
                "s:B": {
                    "create_state": {"country": "c:B", "owned_provinces": "p2"},
                    "add_homeland": "cul_b",
                },
            }
        }
    )
    s.merge_state("s:A", "s:B")


def test_states_dump_bom(tmp_path, states_data):
    p = tmp_path / "s.txt"
    States(states_data).dump(p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
