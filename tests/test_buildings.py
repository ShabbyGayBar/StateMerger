import pytest

from vic3_state_merger.buildings import Building, Buildings

pytestmark = pytest.mark.unit


def own(kind, levels, **kw):
    d = {"type": kind, "country": "c:USA", "levels": levels, "region": '"A"'}
    d.update(kw)
    return d


def test_building_normalizes_and_deduplicates():
    b = Building(
        {
            "building": "b",
            "add_ownership": {"building": [own("x", 2), own("x", "3")]},
            "reserves": "4",
            "activate_production_methods": "pm_a",
        }
    )
    assert (
        b.level_cnt() == 5
        and b.reserves == 4
        and b.activate_production_methods == ["pm_a"]
    )
    assert b.building_ownership[0]["levels"] == 5


def test_building_iadd_categories_and_mismatch():
    a = Building(
        {
            "building": "b",
            "add_ownership": {
                "country": {"country": "c:USA", "levels": 1},
                "company": {"type": "co", "country": "c:USA", "levels": 2},
            },
        }
    )
    b = Building(
        {
            "building": "b",
            "add_ownership": {
                "country": {"country": "c:USA", "levels": 3},
                "company": {"type": "co", "country": "c:USA", "levels": 4},
            },
        }
    )
    a += b
    assert (
        a.country_ownership[0]["levels"] == 4 and a.company_ownership[0]["levels"] == 6
    )
    with pytest.raises(ValueError):
        a += Building({"building": "other"})


def test_monument_and_empty_serialization():
    assert Building({"building": "b", "level": 1}).level_cnt() == 1
    assert Building({}).is_empty()
    assert "level = 1" in str(Building({"building": "b", "level": 1}))


def test_buildings_merge_and_region_retarget(building_data):
    src = Buildings(building_data)
    src["s:B"] = {
        "USA": [
            Building(
                {
                    "building": "building_tooling_workshops",
                    "add_ownership": {
                        "building": own("privately_owned", 3, region='"B"')
                    },
                }
            )
        ]
    }
    src.merge_states({"A": ["B"]})
    assert "s:B" not in src and src["s:A"]["USA"][0].level_cnt() == 5
    src["s:C"] = {
        "USA": [
            Building(
                {
                    "building": "b",
                    "add_ownership": {"building": own("x", 1, region='"C"')},
                }
            )
        ]
    }
    src.merge_states({"A": ["C"]})
    assert src["s:A"]["USA"][-1].building_ownership[0]["region"] == '"A"'


def test_buildings_dump_bom(tmp_path, building_data):
    p = tmp_path / "x.txt"
    Buildings(building_data).dump(p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
