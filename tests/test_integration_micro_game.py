"""End-to-end tests for the committed synthetic Victoria 3 corpus."""

import json
from pathlib import Path

import pyradox
import pytest

from vic3_state_merger.state_merger import StateMerger

FIXTURE = Path(__file__).parent / "fixtures" / "micro_game"
PLAN = {"STATE_ALPHA": ["STATE_BETA"]}
pytestmark = pytest.mark.integration


def _run(root: Path, out: Path, cache: Path) -> None:
    merger = StateMerger(str(root), str(out), PLAN, str(cache))
    merger.merge_state_data()
    merger.merge_misc_data()
    merger.merge_loc_data()


def test_micro_game_pipeline_semantics(tmp_path):
    out = tmp_path / "mod"
    _run(FIXTURE, out, tmp_path / "cache")

    region = (out / "map_data/state_regions/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "STATE_ALPHA" in region
    assert "STATE_BETA" not in region
    assert "xA1" in region and "xB2" in region
    assert "arable_land = 8" in region
    assert "SEA_TEST" not in region and "SEA_OTHER" not in region

    states = (out / "common/history/states/00_states.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "s:STATE_ALPHA" in states and "s:STATE_BETA" not in states
    assert states.count("c:CLAIM_A") == 1
    assert "c:CLAIM_B" in states and "cul_beta" in states

    buildings = (out / "common/history/buildings/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "building_coal_mine" in buildings
    assert "levels = 5" in buildings
    assert 'region = "STATE_ALPHA"' in buildings
    assert 'region = "STATE_BETA"' not in buildings

    pops = (out / "common/history/pops/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "size = 150" in pops
    assert "size = 25" in pops
    assert "s:STATE_BETA" not in pops

    trade = (out / "common/history/trade/00_historical_trade.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "add_exports = 6" in trade and "add_imports = 8" in trade
    assert "coal" in trade

    for name in (
        "generated_map_object_locators_city.txt",
        "generated_map_object_locators_farm.txt",
        "generated_map_object_locators_mine.txt",
        "generated_map_object_locators_port.txt",
        "generated_map_object_locators_wood.txt",
    ):
        text = (out / "gfx/map/map_object_data" / name).read_text(encoding="utf-8-sig")
        assert "id = 77" in text
        assert "id = 2" not in text

    decisions = (out / "common/decisions/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "REPLACE:decision_test" in decisions
    assert "STATE_ALPHA" in decisions
    assert "STATE_BETA_ANJOU" in decisions

    event = (out / "events/01_events.txt").read_text(encoding="utf-8-sig")
    assert "STATE_ALPHA" in event and "STATE_BETA" not in event
    strategic = (out / "common/strategic_regions/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "STATE_ALPHA" in strategic
    assert "STATE_BETA " not in strategic
    assert "STATE_BETA_ANJOU" in strategic

    en = (
        out / "localization/english/hub_names_states_merging_l_english.yml"
    ).read_text(encoding="utf-8-sig")
    zh = (
        out / "localization/simp_chinese/hub_names_states_merging_l_simp_chinese.yml"
    ).read_text(encoding="utf-8-sig")
    assert "HUB_NAME_STATE_ALPHA_port" in en
    assert "Beta Port" in en
    assert "HUB_NAME_STATE_ALPHA_mine" not in zh
    assert "贝塔港" in zh

    assert (out / "common/state_traits/state_merging.txt").exists()
    assert (
        out / "common/flag_definitions/state_merging_flag_definition_usa.txt"
    ).exists()
    assert (out / "common/script_values/state_merging_usa_state_counter.txt").exists()

    for relative in (
        "map_data/state_regions/state_merging.txt",
        "common/history/states/00_states.txt",
        "common/history/buildings/state_merging.txt",
        "common/history/pops/state_merging.txt",
        "common/history/trade/00_historical_trade.txt",
        "gfx/map/map_object_data/generated_map_object_locators_city.txt",
    ):
        assert (
            pyradox.parse_file(
                str(out / relative), game="HoI4", path_relative_to_game=False
            )
            is not None
        )


def test_pipeline_is_byte_deterministic(tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    _run(FIXTURE, out_a, tmp_path / "cache-a")
    stale = out_a / "events" / "stale.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale", encoding="utf-8")
    _run(FIXTURE, out_b, tmp_path / "cache-b")
    _run(FIXTURE, out_a, tmp_path / "cache-a")
    assert not stale.exists()
    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b
    assert all((out_a / p).read_bytes() == (out_b / p).read_bytes() for p in files_a)


def test_fixture_plan_is_valid_json():
    assert json.loads((FIXTURE / "merge_states.json").read_text()) == PLAN


def test_cli_run_merge_micro_game(tmp_path):
    from vic3_state_merger.cli import run_merge

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    output = tmp_path / "cli-mod"
    run_merge(
        str(plan), str(output), str(FIXTURE), str(tmp_path / "cli-cache"), 4, False
    )
    assert (output / "common/history/states/00_states.txt").exists()
