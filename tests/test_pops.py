import pytest

from vic3_state_merger.pops import Pops

pytestmark = pytest.mark.unit


def test_format_and_merge(pops_data):
    p = Pops(pops_data)
    assert isinstance(p["s:A"]["USA"]["create_pop"], list)
    p.merge_states({"A": ["B"]})
    assert "s:B" not in p
    pops = p["s:A"]["USA"]["create_pop"]
    assert any(x["culture"] == "a" and x["size"] == 15 for x in pops)
    assert any(x["culture"] == "b" for x in pops)


def test_optional_attributes_must_match():
    p = Pops(
        {
            "POPS": {
                "s:A": {"T": {"create_pop": [{"culture": "a", "size": 1}]}},
                "s:B": {
                    "T": {"create_pop": [{"culture": "a", "religion": "r", "size": 2}]}
                },
            }
        }
    )
    p.merge_state("s:A", "s:B")
    assert len(p["s:A"]["T"]["create_pop"]) == 2


def test_empty_pop_serialization_and_dump(tmp_path):
    p = Pops({"POPS": {"s:A": {"T": {"create_pop": []}}}})
    assert "create_pop = {}" in p.get_str("s:A")
    out = tmp_path / "p.txt"
    p.dump(out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
