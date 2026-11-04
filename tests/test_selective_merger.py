# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Composable pipelines over original synthetic game and mod data."""

import json
import shutil
from pathlib import Path

import pyradox
import pytest
import yaml

from vic3_state_merger.cli import _execution_options, main, run_merge
from vic3_state_merger.sources import ASSETS, STAGES
from vic3_state_merger.state_merger import StateMerger, _clean_v3_yml_numbered_keys

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).parent / "fixtures" / "micro_game"
OVERLAY = Path(__file__).parent / "fixtures" / "micro_mod"
PLAN = {"STATE_ALPHA": ["STATE_BETA"]}
MAP = "map_data/state_regions"
GENERATED = f"{MAP}/state_merging.txt"


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")
    return path


def inventory(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def regions(out):
    tree = pyradox.parse_file(
        str(out / GENERATED), game="HoI4", path_relative_to_game=False
    )
    assert isinstance(tree, pyradox.Tree)
    return tree.to_python()


def test_constructor_and_properties_are_read_only(tmp_path):
    out = tmp_path / "out"
    keep = write(out, f"{MAP}/keep.txt", "keep")
    merger = StateMerger(FIXTURE, out, PLAN)
    assert inventory(out) == {f"{MAP}/keep.txt": keep.read_bytes()}
    assert "STATE_ALPHA" in merger.map_data and "s:STATE_BETA" in merger.states
    assert "s:STATE_ALPHA" in merger.buildings
    assert "s:STATE_ALPHA" in merger.pops and "s:STATE_ALPHA" in merger.trade
    assert list(out.rglob("*.txt")) == [keep]
    absent = tmp_path / "absent"
    StateMerger(tmp_path / "missing", absent, PLAN)
    assert not absent.exists()


def test_map_only_uses_mod_root_without_any_vanilla_data(tmp_path):
    mod = tmp_path / "source"
    shutil.copytree(FIXTURE / MAP, mod / MAP)
    out = tmp_path / "out"
    merger = StateMerger(
        tmp_path / "missing-game", out, PLAN, sources={"map_data": [mod]}
    )
    merger.run(["map_data"])
    result = regions(out)
    assert result["STATE_ALPHA"]["arable_land"] == 8
    assert "STATE_BETA" not in result
    assert "states_integration" not in (out / GENERATED).read_text(encoding="utf-8-sig")
    assert set(inventory(out)) == {GENERATED, f"{MAP}/01_regions.txt"}
    assert all(data.startswith(b"\xef\xbb\xbf") for data in inventory(out).values())


def test_all_stages_overlay_map_and_keep_vanilla_history(tmp_path):
    out = tmp_path / "out"
    before = inventory(FIXTURE), inventory(OVERLAY)
    merger = StateMerger(FIXTURE, out, PLAN, sources={"map_data": [FIXTURE, OVERLAY]})
    merger.run()
    result = regions(out)
    assert result["STATE_ALPHA"]["arable_land"] == 25
    assert "STATE_GAMMA" in result and "STATE_REMOVED" not in result
    assert "s:STATE_BETA" not in str(merger.states)
    assert "size = 150" in str(merger.pops)
    assert "levels = 5" in str(merger.buildings)
    assert "add_exports = 6" in str(merger.trade)
    assert not (out / "common/state_traits").exists()
    assert before == (inventory(FIXTURE), inventory(OVERLAY))
    assert (out / MAP / "02_extra.txt").read_text(encoding="utf-8-sig") == ""


def test_selected_cleanup_and_repeated_runs(tmp_path):
    out = tmp_path / "out"
    untouched = {
        "common/history/states/copied.txt": "copied history",
        "events/copied.txt": "copied event",
        "localization/english/copied.yml": "copied name",
        "common/state_traits/custom.txt": "custom trait",
        "gfx/map/map_object_data/copied.txt": "copied locator",
    }
    for name, content in untouched.items():
        write(out, name, content)
    write(out, f"{MAP}/stale.txt", "stale")
    merger = StateMerger(FIXTURE, out, PLAN)
    merger.run(["map_data"])
    first = inventory(out)
    assert f"{MAP}/stale.txt" not in first
    for name, content in untouched.items():
        assert (out / name).read_text(encoding="utf-8-sig") == content
    merger.run(["map_data"])
    assert inventory(out) == first
    assert merger.map_data["STATE_ALPHA"].arable_land == 8


@pytest.mark.parametrize("stage", ["state", "pops", "buildings", "trade"])
def test_history_stage_needs_only_its_own_dataset(tmp_path, stage):
    paths = {
        "state": "states",
        "pops": "pops",
        "buildings": "buildings",
        "trade": "trade",
    }
    game = tmp_path / "game"
    relative = f"common/history/{paths[stage]}"
    shutil.copytree(FIXTURE / relative, game / relative)
    out = tmp_path / "out"
    StateMerger(game, out, PLAN).run([stage])
    assert all(path.startswith(relative + "/") for path in inventory(out))
    assert "s:STATE_BETA" not in "".join(
        data.decode("utf-8-sig") for data in inventory(out).values()
    )


@pytest.mark.parametrize("stage", ["map_objects", "localization"])
def test_read_only_map_dependency_leaves_map_output_untouched(tmp_path, stage):
    out = tmp_path / "out"
    write(out, GENERATED, "copied map")
    StateMerger(FIXTURE, out, PLAN).run([stage])
    assert (out / GENERATED).read_text(encoding="utf-8-sig") == "copied map"
    assert not (out / "common").exists()
    if stage == "map_objects":
        text = (
            out / "gfx/map/map_object_data/generated_map_object_locators_port.txt"
        ).read_text(encoding="utf-8-sig")
        assert "id = 1" in text and "id = 2" not in text
    else:
        assert (
            out / "localization/english/hub_names_states_merging_l_english.yml"
        ).exists()


def test_missing_optional_data_is_skipped(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIXTURE / MAP, root / MAP)
    out = tmp_path / "out"
    StateMerger(root, out, PLAN).run(["map_objects", "misc", "localization"])
    assert inventory(out) == {}


@pytest.mark.parametrize(
    "options,plan",
    [
        ({"stages": ["bad"]}, PLAN),
        ({"stages": ["map_data", "trade"]}, PLAN),
        ({"stages": ["map_data"], "assets": ["bad"]}, PLAN),
        ({"stages": ["map_data"], "small_state_limit": -1}, PLAN),
        ({"stages": ["map_data"], "integration_traits": "yes"}, PLAN),
        ({"stages": ["map_data"]}, {"MISSING": ["STATE_BETA"]}),
        ({"stages": ["map_data"]}, {"STATE_ALPHA": ["MISSING"]}),
        ({"stages": ["map_data"]}, {"STATE_ALPHA": ["SEA_TEST"]}),
        ({"stages": ["map_data"]}, {"STATE_ALPHA": ["STATE_ALPHA"]}),
        ({"stages": ["map_data"]}, {"STATE_ALPHA": ["STATE_BETA", "STATE_BETA"]}),
        (
            {"stages": ["map_data"]},
            {"STATE_ALPHA": ["STATE_BETA"], "STATE_BETA": ["STATE_GAMMA"]},
        ),
        ({"stages": ["map_data"]}, {"STATE_ALPHA": "STATE_BETA"}),
        ({"stages": ["map_data"]}, []),
    ],
)
def test_preflight_failure_preserves_existing_output(tmp_path, options, plan):
    root = tmp_path / "root"
    shutil.copytree(FIXTURE / MAP, root / MAP)
    out = tmp_path / "out"
    write(out, f"{MAP}/copied.txt", "copied map")
    before = inventory(out)
    with pytest.raises((ValueError, TypeError)):
        StateMerger(root, out, plan).run(**options)
    assert inventory(out) == before


def test_missing_root_and_input_output_overlap(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="map_data.*searched roots"):
        StateMerger(tmp_path / "missing", out, PLAN).run(["map_data"])
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    before = inventory(game)
    with pytest.raises(ValueError, match="overlaps input root"):
        StateMerger(game, game / "output", PLAN).run(["map_data"])
    assert inventory(game) == before


def test_integration_trait_opt_in_and_asset_isolation(tmp_path):
    out = tmp_path / "out"
    custom = write(out, "common/state_traits/custom.txt", "custom")
    merger = StateMerger(FIXTURE, out, PLAN)
    merger.run(["map_data"], integration_traits=True, assets=["usa_state_counter"])
    assert "state_trait_two_states_integration" in merger.map_data["STATE_ALPHA"].traits
    assert (out / "common/state_traits/state_merging.txt").exists()
    assert (out / "common/script_values/state_merging_usa_state_counter.txt").exists()
    assert custom.read_text(encoding="utf-8-sig") == "custom"
    assert not (out / "common/flag_definitions").exists()
    merger.run(stages=[], assets=ASSETS)
    assert (
        out / "common/flag_definitions/state_merging_flag_definition_usa.txt"
    ).exists()


def test_plain_map_merge_preserves_existing_integration_traits(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIXTURE / MAP, root / MAP)
    path = root / MAP / "01_regions.txt"
    path.write_text(
        path.read_text().replace(
            "state_trait_coastal", "state_trait_three_states_integration"
        )
    )
    out = tmp_path / "out"
    merger = StateMerger(root, out, PLAN)
    merger.run(["map_data"])
    assert (
        "state_trait_three_states_integration" in merger.map_data["STATE_ALPHA"].traits
    )
    assert (
        "state_trait_four_states_integration"
        not in merger.map_data["STATE_ALPHA"].traits
    )
    assert not (out / "common").exists()


def test_pure_sea_generated_filename_is_preserved(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIXTURE / MAP, root / MAP)
    write(root, GENERATED, "SEA_THIRD = { id = 101 provinces = { sea3 } }")
    write(root, f"{MAP}/empty_override.txt", "")
    out = tmp_path / "out"
    StateMerger(root, out, PLAN).run(["map_data"])
    result = regions(out)
    assert result["SEA_TEST"]["provinces"] == "sea1"
    assert result["SEA_THIRD"]["provinces"] == "sea3"
    assert "SEA_OTHER" not in result
    assert (out / MAP / "empty_override.txt").read_text(encoding="utf-8-sig") == ""


def test_misc_overlays_and_cleanup_do_not_require_map(tmp_path):
    out = tmp_path / "out"
    write(out, "events/stale.txt", "stale")
    merger = StateMerger(
        tmp_path / "absent", out, PLAN, sources={"misc": [FIXTURE, OVERLAY]}
    )
    merger.run(["misc"])
    event = (out / "events/01_events.txt").read_text(encoding="utf-8-sig")
    assert (
        "overlay_event" in event
        and "STATE_ALPHA" in event
        and "STATE_BETA" not in event
    )
    decision = (out / "common/decisions/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "REPLACE:overlay_decision" in decision
    assert not (out / "events/stale.txt").exists()
    assert not (out / "map_data").exists()


def test_localization_layer_priority_and_quote_preservation(tmp_path):
    mod = tmp_path / "mod"
    value = 'Beta\'s "New" Port'
    # The later layer wins even though its filename sorts before the vanilla file.
    write(
        mod,
        "localization/english/00_mod.yml",
        "l_english:\n HUB_NAME_STATE_BETA_port:0 " + json.dumps(value) + "\n",
    )
    write(mod, "localization/english/blank.yml", "")
    out = tmp_path / "out"
    StateMerger(FIXTURE, out, PLAN, sources={"localization": [FIXTURE, mod]}).run(
        ["localization"]
    )
    path = out / "localization/english/hub_names_states_merging_l_english.yml"
    assert (
        yaml.safe_load(_clean_v3_yml_numbered_keys(path))["l_english"][
            "HUB_NAME_STATE_ALPHA_port"
        ]
        == value
    )


def test_malformed_late_input_is_detected_before_cleanup(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIXTURE, root)
    write(root, "localization/english/bad.yml", "l_english: []")
    out = tmp_path / "out"
    write(out, f"{MAP}/keep.txt", "keep")
    before = inventory(out)
    with pytest.raises(TypeError, match="localization"):
        StateMerger(root, out, PLAN).run()
    assert inventory(out) == before


def test_cache_helpers_use_resolved_files(tmp_path):
    cache = tmp_path / "cache"
    sources = {stage: [FIXTURE, OVERLAY] for stage in STAGES}
    merger = StateMerger(FIXTURE, tmp_path / "out", PLAN, cache, sources=sources)
    merger.copy_state_data()
    merger.copy_map_object_data()
    assert (cache / "game_file/map_data/01_regions.txt").read_bytes() == (
        OVERLAY / MAP / "01_regions.txt"
    ).read_bytes()
    assert (
        cache / "game_file/map_object_data/generated_map_object_locators_city.txt"
    ).read_bytes() == (
        OVERLAY / "gfx/map/map_object_data/generated_map_object_locators_city.txt"
    ).read_bytes()
    assert not (cache / "game_file/map_data/99_seas.txt").exists()
    assert not (tmp_path / "out").exists()


def test_legacy_wrappers_keep_exposed_merged_models(tmp_path):
    merger = StateMerger(FIXTURE, tmp_path / "out", PLAN)
    merger.merge_state_data()
    merger.merge_misc_data()
    merger.merge_loc_data()
    assert "s:STATE_BETA" not in merger.states
    assert merger.map_data["STATE_ALPHA"].arable_land == 8
    assert "state_trait_two_states_integration" in merger.map_data["STATE_ALPHA"].traits


def test_config_paths_and_field_overrides(tmp_path, monkeypatch):
    config_dir = tmp_path / "configuration"
    config = write(
        config_dir,
        "run.json",
        json.dumps(
            {
                "stages": ["misc"],
                "sources": {"map_data": ["../game", "../mod"], "misc": ["../other"]},
                "integration_traits": True,
                "assets": ["usa_flag"],
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    options = _execution_options(
        config, ["map_data"], {"map_data": ["cli-root"]}, False, []
    )
    assert options["sources"]["map_data"] == ["cli-root"]
    assert options["sources"]["misc"] == [str(tmp_path / "other")]
    assert options["stages"] == ("map_data",) and options["assets"] == ()
    assert options["integration_traits"] is False
    configured = _execution_options(config, None, None, None, None)
    assert configured["sources"]["map_data"] == [
        str(tmp_path / "game"),
        str(tmp_path / "mod"),
    ]


def test_configured_cli_flags_and_real_output(tmp_path, monkeypatch):
    import sys

    out = tmp_path / "out"
    config = write(
        tmp_path,
        "config.json",
        json.dumps(
            {
                "stages": ["map_data"],
                "sources": {"map_data": [str(FIXTURE), str(OVERLAY)]},
                "integration_traits": True,
                "assets": ["usa_flag"],
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "state-merger-cli",
            str(FIXTURE / "merge_states.json"),
            str(FIXTURE),
            str(out),
            "--config",
            str(config),
            "--source",
            f"map_data={FIXTURE}",
            "--source",
            f"map_data={OVERLAY}",
            "--no-integration-traits",
            "--assets",
            "none",
        ],
    )
    main()
    assert regions(out)["STATE_ALPHA"]["arable_land"] == 25
    assert not (out / "common").exists()


def test_configured_api_defaults_to_no_assets(tmp_path):
    out = tmp_path / "out"
    run_merge(
        str(FIXTURE / "merge_states.json"),
        str(out),
        str(FIXTURE),
        None,
        4,
        False,
        sources={"map_data": [FIXTURE, OVERLAY]},
    )
    assert regions(out)["STATE_ALPHA"]["arable_land"] == 25
    assert not (out / "common/state_traits").exists()


def test_duplicate_definitions_are_not_definition_level_overlays(tmp_path):
    mod = tmp_path / "mod"
    write(
        mod,
        f"{MAP}/98_override.txt",
        """STATE_ALPHA = {
 id = 1
 provinces = { xA1 xA2 }
 subsistence_building = building_subsistence_farms
 arable_land = 50
 arable_resources = bg_grain
}
""",
    )
    out = tmp_path / "out"
    merger = StateMerger(FIXTURE, out, PLAN, sources={"map_data": [FIXTURE, mod]})
    # File-level overlays retain the existing pyradox merge semantics. Two
    # differently named files defining the same state are not last-wins mods.
    with pytest.raises(ValueError, match="map_data: cannot load inputs"):
        merger.run(["map_data"])
    assert not out.exists()


def test_empty_locator_override_is_retained(tmp_path):
    mod = tmp_path / "mod"
    relative = "gfx/map/map_object_data/generated_map_object_locators_city.txt"
    write(mod, relative, "")
    out = tmp_path / "out"
    StateMerger(FIXTURE, out, PLAN, sources={"map_objects": [FIXTURE, mod]}).run(
        ["map_objects"]
    )
    assert (out / relative).read_text(encoding="utf-8-sig") == ""


def test_execution_options_preserve_iterators(tmp_path):
    options = _execution_options(
        None, iter(["map_data"]), None, None, iter(["usa_flag"])
    )
    assert options["stages"] == ("map_data",)
    assert options["assets"] == ("usa_flag",)


def test_history_multiple_files_combine_at_existing_parser_depth(tmp_path):
    mod = tmp_path / "mod"
    write(
        mod,
        "common/history/pops/98_extra.txt",
        """POPS = {
 s:STATE_GAMMA = {
  c:TEST = { create_pop = { culture = cul_gamma size = 9 } }
 }
}
""",
    )
    merger = StateMerger(
        FIXTURE, tmp_path / "out", PLAN, sources={"pops": [FIXTURE, mod]}
    )
    merger.run(["pops"])
    assert "s:STATE_GAMMA" in merger.pops
    assert "size = 150" in str(merger.pops) and "size = 9" in str(merger.pops)


def test_hub_localization_ignores_unrelated_non_yaml_text(tmp_path):
    mod = tmp_path / "mod"
    write(
        mod,
        "localization/english/additional.yml",
        """l_english:
 flavor_text:0 "A phrase with "unescaped quotes" in unrelated text."
 HUB_NAME_STATE_BETA_port:0 "Additional # Port"	# trailing comment
""",
    )
    write(mod, "localization/english/header_only.yml", "l_english:\n")
    out = tmp_path / "out"
    StateMerger(FIXTURE, out, PLAN, sources={"localization": [FIXTURE, mod]}).run(
        ["localization"]
    )
    assert "Additional # Port" in (
        out / "localization/english/hub_names_states_merging_l_english.yml"
    ).read_text(encoding="utf-8-sig")
