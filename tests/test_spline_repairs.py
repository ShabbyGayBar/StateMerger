# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Automatic repairs preserve source data and validate only emitted geometry."""

import json
import shutil
import sys
from copy import deepcopy
from typing import Any

import pytest

from tests.test_spline_network import FIXTURE, geography_files
from tests.test_spline_placement import port_case
from tests.test_spline_validation import land_case
from vic3_state_merger.cli import _execution_options, get_parser, main, run_merge
from vic3_state_merger.splines import (
    Anchor,
    Geography,
    SplineNetwork,
    export_spline_review,
)
from vic3_state_merger.splines.geography import build_geography
from vic3_state_merger.splines.merge import _Merger, merge_spline_network
from vic3_state_merger.splines.network import (
    INTERMEDIATE,
    NAVAL,
    NETWORK_PATH,
    Connection,
    Strip,
    connection_id,
)
from vic3_state_merger.state_merger import StateMerger

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("use_locator", [False, True])
def test_port_relocation_preserves_routes_harbor_and_inputs(
    tmp_path, repair, use_locator, caplog
):
    args = port_case(tmp_path)
    args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    intermediate = INTERMEDIATE | 7
    args[0].anchors[intermediate] = Anchor(intermediate, 1.25, 1.5)
    strip = args[0].connections[connection_id(100, 203, 1)].strips[0]
    args[0].strips[strip] = Strip(strip, (100, intermediate, 203))
    # Supply the same sparse province evidence as the filesystem pipeline.
    args[-1].province_spans = {1: [(0, 0, 3), (1, 0, 0)]}
    if use_locator:
        for tables in (args[3], args[4]):
            tables["port"]["game_object_locator"]["instances"][0]["position"] = [
                1.75,
                1.75,
            ]
        args[-1].province_samples[(1, 0)] = 1
    before = deepcopy(args)
    result = merge_spline_network(*args, repair_splines=repair)
    expected = (1.75, 1.75) if use_locator else (2.5, 1.5)
    assert result.network.anchors[103] == Anchor(
        103, *(expected if repair else (2.25, 0.5))
    )
    assert result.network.anchors[NAVAL | 100] == Anchor(NAVAL | 100, 2.5, 0.5)
    assert connection_id(100, 103, 1) in result.network.connections
    assert result.network.anchors[intermediate] == args[0].anchors[intermediate]
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) in result.network.connections
    assert result.status == ("complete" if repair else "draft")
    assert args == before
    assert merge_spline_network(*args, repair_splines=repair).data == result.data
    result.network.validate_references()
    if repair:
        assert "port_relocated" in caplog.text


@pytest.mark.parametrize(
    "wrap,origin,expected",
    [
        (False, (4, 1), (2.5, 1.5)),
        (True, (4, 1), (0.5, 1.5)),
        (False, (1.5, 1), (0.5, 1.5)),
    ],
)
def test_nearest_pixel_wrap_and_ties(wrap, origin, expected):
    geo = Geography(
        size=(4, 2),
        wrap_x=wrap,
        province_spans={1: [(0, 0, 0), (0, 2, 2), (1, 0, 0), (1, 2, 2)]},
    )
    assert geo.nearest_province_position(1, *origin) == expected
    assert geo.nearest_province_position(2, *origin) is None
    assert geo.nearest_province_position(1, float("nan"), 1) is None


def test_sparse_spans_use_current_raster_with_cached_boundaries(tmp_path):
    files = geography_files(tmp_path, [1, 1, 2, 255, 1, 255, 2, 255], (4, 2))
    for _ in range(2):
        geo = build_geography(
            *files, {}, tmp_path / "cache", relocation_provinces=[1, 2]
        )
        assert geo.province_samples == {}
        assert geo.province_spans == {
            1: [(0, 0, 1), (1, 0, 0)],
            2: [(0, 2, 2), (1, 2, 2)],
        }
        assert geo.province_at(0.5, 1.5) == 1
        assert geo.province_at(2.5, 0.5) == 2
    assert build_geography(*files, {}, tmp_path / "cache").province_spans == {}


@pytest.mark.parametrize("problem", ["noncoastal", "unavailable", "no_target"])
def test_unrepairable_port_is_preserved(tmp_path, problem, caplog):
    args = port_case(tmp_path)
    args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    if problem == "noncoastal":
        args[-1].coastal_provinces.clear()
    elif problem == "unavailable":
        args[-1].placement_available = False
    result = merge_spline_network(*args)
    assert result.network.anchors[103] == Anchor(103, 2.25, 0.5)
    assert result.status == "draft"
    assert "spline_repair_skipped" in caplog.text


def test_relocation_checks_float32_locator_before_using_it(tmp_path):
    args = port_case(tmp_path)
    args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    args[-1].province_spans = {1: [(0, 0, 3), (1, 0, 0)]}
    # Python float is land, emitted float32 rounds onto the sea row.
    for tables in (args[3], args[4]):
        tables["port"]["game_object_locator"]["instances"][0]["position"] = [
            2.25,
            1.00000001,
        ]
    result = merge_spline_network(*args)
    assert result.network.anchors[103] == Anchor(103, 2.5, 1.5)
    assert result.status == "complete"


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize(
    "kind", ["nonadjacent", "incompatible", "unknown", "strait", "uncertain"]
)
def test_connection_repairs_respect_evidence(repair, kind):
    args = land_case(
        [(100, 200, 5 if kind == "unknown" else 1, ())], farm=False, required=()
    )
    if kind == "incompatible":
        args[0].anchors[NAVAL | 10] = Anchor(NAVAL | 10, 1, 1)
        args[0].strips[1] = Strip(1, (100, NAVAL | 10, 200))
    elif kind == "strait":
        args[-1].straits[("A", "B")] = [{"kind": "strait"}]
    elif kind == "uncertain":
        args[-1].adjacency_available = False
    before = deepcopy(args)
    result = merge_spline_network(*args, repair_splines=repair)
    removed = repair and kind in ("nonadjacent", "incompatible")
    assert bool(result.network.connections) is not removed
    assert bool(result.network.strips) is not removed
    assert not removed or set(result.network.anchors) == {100, 200}
    assert args == before
    result.network.validate_references()
    assert merge_spline_network(*args, repair_splines=repair).data == result.data


def test_cleanup_keeps_shared_strips_and_removes_only_orphan_intermediates():
    args = land_case([], farm=False, required=())
    merger = _Merger(*args, repair_splines=True)
    orphan, shared = INTERMEDIATE | 1, INTERMEDIATE | 2
    merger.out = SplineNetwork(
        anchors={n: Anchor(n, 0, 1) for n in (100, 200, 300, orphan, shared)},
        strips={1: Strip(1, (100, shared, 200)), 257: Strip(257, (200, orphan, 300))},
        connections={
            connection_id(100, 200, 1): Connection(connection_id(100, 200, 1), (1,)),
            connection_id(100, 300, 1): Connection(
                connection_id(100, 300, 1), (1, 257)
            ),
        },
    )
    merger.final["C"] = {"id": 3, "city": "x03"}
    merger.geo.straits[("A", "B")] = []
    merger.repair_connections()
    assert set(merger.out.strips) == {1}
    assert shared in merger.out.anchors and orphan not in merger.out.anchors
    assert 300 in merger.out.anchors
    merger.out.validate_references()


def test_naval_connection_with_land_geometry_is_removed_but_missing_route_remains(
    tmp_path, spline_logs
):
    args = port_case(tmp_path)
    identity = connection_id(NAVAL | 200, NAVAL | 9900, 3)
    strip = args[0].connections[identity].strips[0]
    args[0].strips[strip] = Strip(strip, (NAVAL | 200, 203, NAVAL | 9900))
    result = merge_spline_network(*args)
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) not in result.network.connections
    assert connection_id(NAVAL | 9900, NAVAL | 9800, 2) in result.network.connections
    assert NAVAL | 100 in result.network.anchors
    assert result.status == "draft"
    assert "missing_harbor_connection" in {i["kind"] for i in spline_logs("game_rule")}
    assert "incompatible_anchor_type" not in {
        i["kind"] for i in spline_logs("game_rule")
    }
    result.network.validate_references()


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("position", [(1, 1), (-1, -1), None])
def test_missing_hub_policy_is_independent_of_repair_switch(repair, position):
    args = land_case([], required=())
    del args[0].anchors[101]
    instances = args[4]["farm"]["game_object_locator"]["instances"]
    if position is None:
        instances.clear()
    else:
        instances[0]["position"] = list(position)
    result = merge_spline_network(*args, repair_splines=repair)
    assert (101 in result.network.anchors) == (position == (1, 1))


def test_config_cli_defaults_and_boolean_validation(tmp_path):
    parser = get_parser()
    assert parser.parse_args(["p", "g", "m"]).repair_splines is None
    assert (
        parser.parse_args(["p", "g", "m", "--no-repair-splines"]).repair_splines
        is False
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"repair_splines": False}))
    assert _execution_options(config, None, None, None, None)["repair_splines"] is False
    assert (
        _execution_options(config, None, None, None, None, True)["repair_splines"]
        is True
    )
    config.write_text(json.dumps({"repair_splines": "false"}))
    with pytest.raises(ValueError, match="boolean"):
        _execution_options(config, None, None, None, None)
    with pytest.raises(TypeError, match="boolean"):
        invalid: Any = "false"
        merge_spline_network(*land_case([]), repair_splines=invalid)


@pytest.mark.integration
@pytest.mark.parametrize("repair", [False, True])
def test_pipeline_and_review_export_repair_without_changing_inputs(tmp_path, repair):
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    path = game / NETWORK_PATH
    source = SplineNetwork.from_bytes(path.read_bytes())
    source.anchors[203] = Anchor(203, 2, 0.5)
    path.write_bytes(source.to_bytes())
    before = {p: p.read_bytes() for p in game.rglob("*") if p.is_file()}
    plan = {"STATE_ALPHA": ["STATE_BETA"]}
    mod = tmp_path / "mod"
    merger = StateMerger(game, mod, plan, tmp_path / "data")
    merger.run(repair_splines=repair)
    assert merger.spline_result is not None
    assert merger.spline_result.status == ("complete" if repair else "draft")
    review = export_spline_review(
        game,
        mod,
        plan,
        tmp_path / "review",
        tmp_path / "review_data",
        repair_splines=repair,
    )
    assert review.data == merger.spline_result.data
    assert all(p.read_bytes() == contents for p, contents in before.items())


@pytest.mark.integration
@pytest.mark.parametrize("repair", [False, True])
def test_repair_option_alone_preserves_compensation_defaults(tmp_path, repair):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"STATE_ALPHA": ["STATE_BETA"]}))
    out = tmp_path / "mod"
    run_merge(
        str(plan),
        str(out),
        str(FIXTURE),
        str(tmp_path / "data"),
        4,
        False,
        repair_splines=repair,
    )
    assert "state_trait_two_states_integration" in (
        out / "map_data/state_regions/state_merging.txt"
    ).read_text(encoding="utf-8-sig")
    assert (out / "common/state_traits/state_merging.txt").exists()


@pytest.mark.integration
@pytest.mark.parametrize("disable", [False, True])
def test_cli_repair_flag_controls_export_and_exit_code(tmp_path, monkeypatch, disable):
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    path = game / NETWORK_PATH
    source = SplineNetwork.from_bytes(path.read_bytes())
    source.anchors[203] = Anchor(203, 2, 0.5)
    path.write_bytes(source.to_bytes())
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"STATE_ALPHA": ["STATE_BETA"]}))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"stages": ["spline_network"], "repair_splines": True})
    )
    out = tmp_path / "mod"
    argv = ["state-merger", str(plan), str(game), str(out), "--config", str(config)]
    if disable:
        argv.append("--no-repair-splines")
    monkeypatch.setattr(sys, "argv", argv)
    if disable:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 3
    else:
        main()
    emitted = SplineNetwork.from_bytes((out / NETWORK_PATH).read_bytes())
    assert (emitted.anchors[103] == Anchor(103, 2, 0.5)) is disable


@pytest.mark.integration
def test_disabled_spline_stage_does_not_prepare_repairs(tmp_path):
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    (game / NETWORK_PATH).unlink()
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"STATE_ALPHA": ["STATE_BETA"]}))
    out = tmp_path / "mod"
    result = run_merge(
        str(plan),
        str(out),
        str(game),
        str(tmp_path / "data"),
        4,
        False,
        spline_network=False,
        repair_splines=True,
    )
    assert result is None
    assert not (out / NETWORK_PATH).exists()
