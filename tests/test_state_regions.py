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
        and r.gold == [4, 2]
        and r.oil == 5
        and r.capped_resources["building_iron_mine"] == 3
    )


def test_region_merge_additive_fallback_and_clear():
    a = StateRegionItem(
        "A",
        land("A", 1, ["a"], arable_land=2, arable_resources=["x"], city="", gold=[]),
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
