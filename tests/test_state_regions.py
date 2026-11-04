# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

from copy import deepcopy

import pyradox
import pytest

from vic3_state_merger.state_regions import StateRegion, StateRegionItem

pytestmark = pytest.mark.unit


def land(name, ident, provinces, **kw):
    d = {
        "id": ident,
        "subsistence_building": "building_subsistence_farms",
        "provinces": provinces,
        "arable_land": 2,
        "arable_resources": ["bg_ranches"],
    }
    d.update(kw)
    return {name: d}


def test_region_constructor_and_properties():
    r = StateRegionItem(
        "A",
        land(
            "A",
            "1",
            ["p1", "p2"],
            impassable="p0",
            traits="state_trait_one_states_integration",
            capped_resources={"building_iron_mine": "3"},
            resource=[
                {
                    "type": "building_gold_field",
                    "undiscovered_amount": "4",
                    "discovered_amount": 2,
                },
                {"type": "building_oil_rig", "undiscovered_amount": 5},
            ],
            city="p1",
        ),
    )
    assert r.id == 1 and r.province_cnt() == 2 and r.is_small_state()
    assert (
        r.merge_states_cnt() == 1
        and r.resources["building_gold_field"]
        == {"undiscovered_amount": 4, "discovered_amount": 2}
        and r.resources["building_oil_rig"] == {"undiscovered_amount": 5}
        and r.capped_resources["building_iron_mine"] == 3
    )


def test_region_merge_additive_fallback_and_clear():
    a = StateRegionItem(
        "A",
        land("A", 1, ["a"], arable_land=2, arable_resources=["x"], city=""),
    )
    b = StateRegionItem(
        "B",
        land(
            "B",
            2,
            ["b"],
            arable_land=3,
            arable_resources=["x", "y"],
            city="bc",
            capped_resources={"iron": 2},
            naval_exit_id=7,
        ),
    )
    a.merge(b)
    assert (
        a.provinces == ["a", "b"]
        and a.arable_land == 5
        and a.arable_resources == ["x", "y"]
    )
    assert a.city == "bc" and a.capped_resources["iron"] == 2 and a.naval_exit_id == 7
    assert b.provinces == [] and b.arable_land == 0


def test_sea_node_is_not_merged():
    sea = StateRegionItem("SEA", {"SEA": {"id": 9, "provinces": ["s"]}})
    land_r = StateRegionItem("A", land("A", 1, ["a"]))
    sea.merge(land_r)
    assert sea.is_sea_node() and sea.provinces == ["s"]


def test_collection_merge_and_outputs():
    r = StateRegion(
        {
            **land("A", 1, ["a"]),
            **land("B", 2, ["b"]),
            "SEA": {"id": 3, "provinces": ["s"]},
        }
    )
    ids = r.merge_states({"A": ["B"]})
    assert ids == {1: [2]} and "B" not in r and r.provinces_count_dict()["A"] == 2
    assert "SEA" not in str(r) and "SEA" in r.__str__(include_sea_nodes=True)


def test_region_dump_bom(tmp_path):
    p = tmp_path / "r.txt"
    StateRegion(land("A", 1, ["a"])).dump(p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    "kind",
    [
        "building_gold_field",
        "building_rubber_plantation",
        "building_oil_rig",
        "building_coal_mine",
        "building_iron_mine",
        "building_lead_mine",
        "building_sulfur_mine",
        "building_custom_mine",
    ],
)
def test_generic_resource_quantities(kind):
    a = StateRegionItem(
        "A", land("A", 1, ["a"], resource={"type": kind, "discovered_amount": "2"})
    )
    b = StateRegionItem(
        "B",
        land(
            "B",
            2,
            ["b"],
            resource=[
                {"type": kind, "undiscovered_amount": "3"},
                {"type": kind, "undiscovered_amount": 4, "discovered_amount": 1},
            ],
        ),
    )
    assert a.resources == {kind: {"discovered_amount": 2}}
    assert b.resources == {kind: {"undiscovered_amount": 7, "discovered_amount": 1}}
    a.merge(b)
    assert a.resources == {kind: {"discovered_amount": 3, "undiscovered_amount": 7}}
    assert b.resources == {}
    assert "resource" not in b.to_python()
    assert not any(hasattr(a, attr) for attr in ("gold", "rubber", "oil"))


@pytest.mark.parametrize("resources", [None, []])
def test_absent_or_empty_resources(resources):
    source = land("A", 1, ["a"])
    if resources is not None:
        source["A"]["resource"] = resources
    a = StateRegionItem("A", source)
    assert a.resources == {}
    assert "resource" not in a.to_python()
    assert "resource =" not in str(a)


def test_resource_metadata_union_and_isolation():
    source = land(
        "A",
        1,
        ["a"],
        resource={
            "type": "building_gold_field",
            "discovered_amount": "0",
            "custom": {"label": "gold deposit", "enabled": True},
        },
    )
    original = deepcopy(source)
    a = StateRegionItem("A", source)
    assert source == original
    b = StateRegionItem(
        "B",
        land(
            "B",
            2,
            ["b"],
            resource=[
                {
                    "type": "building_gold_field",
                    "depleted_type": "building_custom_gold_mine",
                    "custom": {"label": "gold deposit", "enabled": True},
                },
                {"type": "building_custom_mine", "custom": {"enabled": False}},
            ],
        ),
    )
    old_a = a.resources
    old_b = b.resources
    a.merge(b)
    assert a.resources == {
        "building_gold_field": {
            "discovered_amount": 0,
            "custom": {"label": "gold deposit", "enabled": True},
            "depleted_type": "building_custom_gold_mine",
        },
        "building_custom_mine": {"custom": {"enabled": False}},
    }
    old_a["building_gold_field"]["custom"]["label"] = "old diner"
    old_b["building_custom_mine"]["custom"]["enabled"] = True
    source["A"]["resource"]["custom"]["label"] = "input"
    source["A"]["provinces"].append("input province")
    assert a.provinces == ["a", "b"]
    assert a.resources["building_gold_field"]["custom"]["label"] == "gold deposit"
    assert a.resources["building_custom_mine"]["custom"]["enabled"] is False
    assert b.resources == {}

    exported = a.to_python()
    assert exported["resource"][0]["discovered_amount"] == 0
    assert "undiscovered_amount" not in exported["resource"][0]
    exported["resource"][0]["custom"]["label"] = "export"
    exported["resource"][1]["custom"]["enabled"] = True
    assert a.resources["building_gold_field"]["custom"]["label"] == "gold deposit"
    assert a.resources["building_custom_mine"]["custom"]["enabled"] is False


@pytest.mark.parametrize(
    "field,left,right",
    [
        ("depleted_type", "building_gold_mine", "building_other_mine"),
        ("custom", {"enabled": True}, {"enabled": False}),
    ],
)
def test_conflicting_resource_metadata_leaves_both_states_unchanged(field, left, right):
    regions = StateRegion(
        {
            **land(
                "A",
                1,
                ["a"],
                resource={"type": "building_gold_field", field: left},
            ),
            **land(
                "B",
                2,
                ["b"],
                resource=[
                    {"type": "building_custom_mine", "discovered_amount": 7},
                    {
                        "type": "building_gold_field",
                        "discovered_amount": 5,
                        field: right,
                    },
                ],
            ),
        }
    )
    before = {name: deepcopy(vars(state)) for name, state in regions.items()}
    with pytest.raises(ValueError) as exc:
        regions.merge_state("A", "B")
    assert all(s in str(exc.value) for s in ("A", "B", "building_gold_field", field))
    assert {name: vars(state) for name, state in regions.items()} == before


def test_duplicate_resource_metadata_conflict_does_not_change_input():
    source = land(
        "A",
        1,
        ["a"],
        resource=[
            {"type": "building_gold_field", "depleted_type": "building_gold_mine"},
            {"type": "building_gold_field", "depleted_type": "building_other_mine"},
        ],
    )
    original = deepcopy(source)
    with pytest.raises(ValueError, match=r"A: building_gold_field\.depleted_type"):
        StateRegionItem("A", source)
    assert source == original


@pytest.mark.parametrize("multiple", [False, True])
def test_resources_round_trip(tmp_path, multiple):
    blocks = [
        {
            "type": "building_gold_field",
            "discovered_amount": 0,
            "custom": {"label": "rich deposit", "enabled": True},
        },
    ]
    if multiple:
        blocks.extend(
            [
                {"type": "building_iron_mine", "undiscovered_amount": 0},
                {
                    "type": "building_custom_mine",
                    "depleted_type": "building_other_mine",
                },
                {"type": "building_oil_rig", "discovered_amount": 6},
            ]
        )
    regions = StateRegion(land("A", 1, ["a", "b"], resource=blocks))
    assert regions["A"].to_python()["resource"] == blocks
    assert "depleted_type" not in regions["A"].resources["building_gold_field"]
    assert StateRegion(regions.to_python())["A"].resources == regions["A"].resources

    path = tmp_path / "regions.txt"
    regions.dump(path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_text(encoding="utf-8-sig").count("resource = {") == len(blocks)
    parsed = StateRegion(
        pyradox.parse_file(str(path), game="HoI4", path_relative_to_game=False)
    )
    assert parsed["A"].resources == regions["A"].resources
    assert list(parsed["A"].resources) == [block["type"] for block in blocks]
