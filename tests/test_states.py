# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

from copy import deepcopy

import pyradox
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


def _tree_signature(tree):
    """Compare ordered entries, scalar types, and operators recursively."""
    return [
        (
            key,
            tree.get_operator_at(index),
            _tree_signature(value)
            if isinstance(value, pyradox.Tree)
            else (type(value), value),
        )
        for index, (key, value) in enumerate(tree.items())
    ]


def test_script_tree_round_trip_preserves_order_operators_and_lists():
    source = pyradox.parse("""STATES = {
        s:A = {
            set_variable = { name = daimyo_chain_id value = 0 }
            if = {
                limit = { var:daimyo_chain_id >= 0 var:daimyo_chain_id < 2 }
                set_variable = { name = label value = "original label" }
                random_list = { 10 = { sample_effect = yes } 20 = { other_effect = no } }
            }
            set_variable = { name = daimyo_chain_id value = 3 }
            else_if = { limit = { flag = no } sample_effect = yes }
            else = { sample_effect = no }
            if = { limit = { s:STATE_OTHER = { exists = yes } } sample_effect = yes }
            sample_list = { first "second entry" third }
            empty_list = { }
        }
    }""")
    states = States(source)
    serialized = str(states)
    reparsed = pyradox.parse(serialized)["STATES"]["s:A"]
    assert states["s:A"]["create_state"] == []
    assert _tree_signature(reparsed) == _tree_signature(source["STATES"]["s:A"])
    assert 'sample_list = { first "second entry" third' in serialized
    assert reparsed["empty_list"].to_python() == {}
    assert str(States(pyradox.parse(serialized))) == serialized


@pytest.mark.parametrize(
    "value", ['"0"', '"yes"', '"1836.1.1"', "0.123456", "0.0000001"]
)
def test_script_values_keep_types_and_precision(value):
    source = pyradox.parse(
        "STATES = { s:A = { set_variable = { name = sample value = " + value + " } } }"
    )
    states = States(source)
    serialized = str(states)
    assert _tree_signature(pyradox.parse(serialized)) == _tree_signature(source)
    assert str(states) == serialized


@pytest.mark.parametrize("sequence", [list, tuple])
def test_dictionary_scripts_support_repeated_assignments_and_nested_blocks(sequence):
    source = {
        "STATES": {
            "s:A": {
                "set_variable": sequence(
                    [
                        {"name": "daimyo_chain_id", "value": 0},
                        {"name": "sample", "value": "quoted value"},
                    ]
                ),
                "if": {"limit": {"exists": True}, "sample_effect": sequence([1, 2])},
            }
        }
    }
    original = deepcopy(source)
    states = States(source)
    parsed = pyradox.parse(str(states))["STATES"]["s:A"]
    assert parsed.count("set_variable") == 2
    assert parsed.to_python() == original["STATES"]["s:A"] | {
        "set_variable": list(original["STATES"]["s:A"]["set_variable"]),
        "if": {"limit": {"exists": True}, "sample_effect": [1, 2]},
    }
    assert source == original


@pytest.mark.parametrize("survivor_has_script", [False, True])
def test_scripts_append_in_plan_order_without_deduplication(survivor_has_script):
    source = pyradox.parse("""STATES = {
        s:A = { }
        s:B = { set_variable = { name = daimyo_chain_id value = 0 } donor_effect = yes }
        s:C = { set_variable = { name = daimyo_chain_id value = 2 } }
        s:D = { set_variable = { name = daimyo_chain_id value = 0 } }
    }""")
    if survivor_has_script:
        source["STATES"]["s:A"].append(
            "set_variable", {"name": "daimyo_chain_id", "value": 0}
        )
    states = States(source)
    states.merge_states({"A": ["C", "B", "D"]})
    parsed = pyradox.parse(str(states))["STATES"]["s:A"]
    expected_values = ([0] if survivor_has_script else []) + [2, 0, 0]
    assert [
        block["value"] for block in parsed.find_all("set_variable")
    ] == expected_values
    assert list(parsed.keys()) == (
        (["set_variable"] if survivor_has_script else [])
        + ["set_variable", "set_variable", "donor_effect", "set_variable"]
    )
    assert list(states) == ["s:A"]
    assert [
        block["value"] for block in states["s:A"]["set_variable"]
    ] == expected_values


@pytest.mark.parametrize("dictionary_source", [False, True])
def test_captured_and_merged_scripts_are_independent(dictionary_source):
    tree = pyradox.parse("""STATES = {
        s:A = { }
        s:B = { if = { set_variable = { name = sample value = 0 } } }
    }""")
    source = tree.to_python() if dictionary_source else tree
    states = States(source)
    independent = States(source)
    source["STATES"]["s:B"]["if"]["set_variable"]["value"] = 99
    states.merge_state("s:A", "s:B")
    assert (
        pyradox.parse(states.get_str("s:A"))["s:A"]["if"]["set_variable"]["value"] == 0
    )
    # Mutating either the donor's exposed data or its retained tree must not
    # change the survivor or a separately constructed States instance.
    states["s:B"]["if"]["set_variable"]["value"] = 88
    states._script_clauses["s:B"]["if"]["set_variable"]["value"] = 77
    assert (
        pyradox.parse(states.get_str("s:A"))["s:A"]["if"]["set_variable"]["value"] == 0
    )
    assert (
        pyradox.parse(str(independent))["STATES"]["s:B"]["if"]["set_variable"]["value"]
        == 0
    )


def test_scripts_follow_modeled_fields(states_data):
    states_data["STATES"]["s:A"]["set_variable"] = {"name": "sample", "value": 0}
    parsed = pyradox.parse(str(States(states_data)))["STATES"]["s:A"]
    assert list(parsed.keys()) == [
        "create_state",
        "add_homeland",
        "add_claim",
        "set_variable",
    ]
