"""Tests for the hub inheritance / hub_overrides feature."""

import json
import os
import tempfile

import pytest

from vic3_state_merger.cli import load_merge_config
from vic3_state_merger.state_regions import StateRegion, StateRegionItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_dict(name: str, province: str, city: str = "", port: str = "", farm: str = "",
                     mine: str = "", wood: str = "", state_id: int = 1) -> dict:
    """Return a minimal state-region dict suitable for constructing a StateRegionItem."""
    return {
        name: {
            "id": state_id,
            "subsistence_building": "building_subsistence_farms",
            "provinces": [province],
            "arable_land": 10,
            "arable_resources": ["bg_wheat_farms"],
            **({"city": city} if city else {}),
            **({"port": port} if port else {}),
            **({"farm": farm} if farm else {}),
            **({"mine": mine} if mine else {}),
            **({"wood": wood} if wood else {}),
        }
    }


def _make_region(states: list[tuple]) -> StateRegion:
    """Build a StateRegion from a list of (name, id, province, city, port, farm, mine, wood) tuples."""
    region = StateRegion()
    for idx, (name, prov, city, port, farm, mine, wood) in enumerate(states, start=1):
        d = _make_state_dict(name, prov, city=city, port=port, farm=farm, mine=mine, wood=wood, state_id=idx)
        region[name] = StateRegionItem(name, d)
    return region


# ---------------------------------------------------------------------------
# Tests for load_merge_config
# ---------------------------------------------------------------------------

class TestLoadMergeConfig:
    def test_old_list_format(self, tmp_path):
        """Old-style list values are parsed correctly and produce no hub_overrides."""
        data = {"STATE_A": ["STATE_B", "STATE_C"], "STATE_D": []}
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        merge_dict, hub_overrides = load_merge_config(str(p))

        assert merge_dict == {"STATE_A": ["STATE_B", "STATE_C"], "STATE_D": []}
        assert hub_overrides == {}

    def test_new_dict_format(self, tmp_path):
        """New-style dict values are parsed into merge_dict and hub_overrides."""
        data = {
            "STATE_A": {
                "merge": ["STATE_B", "STATE_C"],
                "city": "STATE_B",
                "port": "STATE_C",
            }
        }
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        merge_dict, hub_overrides = load_merge_config(str(p))

        assert merge_dict == {"STATE_A": ["STATE_B", "STATE_C"]}
        assert hub_overrides == {"STATE_A": {"city": "STATE_B", "port": "STATE_C"}}

    def test_mixed_format(self, tmp_path):
        """Old and new style values can coexist in the same file."""
        data = {
            "STATE_A": {
                "merge": ["STATE_B"],
                "mine": "STATE_B",
            },
            "STATE_D": ["STATE_E"],
            "STATE_F": [],
        }
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        merge_dict, hub_overrides = load_merge_config(str(p))

        assert merge_dict == {"STATE_A": ["STATE_B"], "STATE_D": ["STATE_E"], "STATE_F": []}
        assert hub_overrides == {"STATE_A": {"mine": "STATE_B"}}

    def test_dict_without_hub_overrides(self, tmp_path):
        """A dict value with only a 'merge' key produces no hub_overrides entry."""
        data = {"STATE_A": {"merge": ["STATE_B"]}}
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        merge_dict, hub_overrides = load_merge_config(str(p))

        assert merge_dict == {"STATE_A": ["STATE_B"]}
        assert hub_overrides == {}

    def test_invalid_value_raises(self, tmp_path):
        """A non-list, non-dict value raises ValueError."""
        data = {"STATE_A": "not_a_list_or_dict"}
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="STATE_A"):
            load_merge_config(str(p))

    def test_non_hub_keys_ignored(self, tmp_path):
        """Unknown keys in the dict format are not included in hub_overrides."""
        data = {"STATE_A": {"merge": ["STATE_B"], "city": "STATE_B", "unknown_key": "STATE_B"}}
        p = tmp_path / "merge.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        _, hub_overrides = load_merge_config(str(p))

        assert "unknown_key" not in hub_overrides.get("STATE_A", {})
        assert hub_overrides == {"STATE_A": {"city": "STATE_B"}}


# ---------------------------------------------------------------------------
# Tests for StateRegion.merge_states with hub_overrides
# ---------------------------------------------------------------------------

class TestMergeStatesHubOverrides:
    def _build_region(self):
        """Build a region with three states: A (diner), B and C (food).

        Hub layout:
            STATE_A: city=x1, port=(none),  farm=x1,  mine=(none), wood=(none)
            STATE_B: city=x2, port=x2,      farm=(none), mine=x2,  wood=(none)
            STATE_C: city=x3, port=x3,      farm=x3,  mine=(none), wood=x3
        """
        return _make_region([
            # name,       province,  city,      port,      farm,      mine,      wood
            ("STATE_A", "x000001", "x000001", "",        "x000001", "",        ""),
            ("STATE_B", "x000002", "x000002", "x000002", "",        "x000002", ""),
            ("STATE_C", "x000003", "x000003", "x000003", "x000003", "",        "x000003"),
        ])

    def test_default_merge_no_overrides(self):
        """Without hub_overrides, default merge logic is used."""
        region = self._build_region()
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}
        region.merge_states(merge_dict)

        # port: A had no port, B has port → A.port == B's original port
        assert region["STATE_A"].port == "x000002"
        # mine: A had no mine, B has mine
        assert region["STATE_A"].mine == "x000002"
        # wood: A had no wood, C has wood
        assert region["STATE_A"].wood == "x000003"
        # city: A keeps its own city (city is never propagated)
        assert region["STATE_A"].city == "x000001"

    def test_hub_override_city(self):
        """hub_overrides for city changes the merged state's city hub."""
        region = self._build_region()
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}
        hub_overrides = {"STATE_A": {"city": "STATE_B"}}

        region.merge_states(merge_dict, hub_overrides=hub_overrides)

        assert region["STATE_A"].city == "x000002"  # overridden to STATE_B's city

    def test_hub_override_port(self):
        """hub_overrides for port overrides the default merge result."""
        region = self._build_region()
        # STATE_A originally has no port; default merge would give it STATE_B's port.
        # Override to use STATE_C's port instead.
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}
        hub_overrides = {"STATE_A": {"port": "STATE_C"}}

        region.merge_states(merge_dict, hub_overrides=hub_overrides)

        assert region["STATE_A"].port == "x000003"  # STATE_C's port

    def test_hub_override_keeps_diner_hub(self):
        """hub_overrides referencing the diner state restores its original hub."""
        region = self._build_region()
        # STATE_A has city "x000001". Override specifies STATE_A as source → keep it.
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}
        hub_overrides = {"STATE_A": {"city": "STATE_A"}}

        region.merge_states(merge_dict, hub_overrides=hub_overrides)

        assert region["STATE_A"].city == "x000001"

    def test_hub_override_multiple_hubs(self):
        """Multiple hub types can be overridden simultaneously."""
        region = self._build_region()
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}
        hub_overrides = {
            "STATE_A": {
                "city": "STATE_C",   # x000003
                "mine": "STATE_B",   # x000002
                "wood": "STATE_C",   # x000003
            }
        }

        region.merge_states(merge_dict, hub_overrides=hub_overrides)

        assert region["STATE_A"].city == "x000003"
        assert region["STATE_A"].mine == "x000002"
        assert region["STATE_A"].wood == "x000003"

    def test_hub_override_unknown_source_warns(self, capsys):
        """An override referencing a non-existent state prints a warning and is skipped."""
        region = self._build_region()
        merge_dict = {"STATE_A": ["STATE_B"]}
        hub_overrides = {"STATE_A": {"city": "STATE_NONEXISTENT"}}

        region.merge_states(merge_dict, hub_overrides=hub_overrides)

        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "STATE_NONEXISTENT" in captured.out

    def test_no_hub_overrides_backward_compat(self):
        """Calling merge_states without hub_overrides parameter works as before."""
        region = self._build_region()
        merge_dict = {"STATE_A": ["STATE_B", "STATE_C"]}

        region.merge_states(merge_dict)  # no hub_overrides kwarg

        # Default behavior: A's port comes from B (first state with a port)
        assert region["STATE_A"].port == "x000002"
