# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authored endpoints and coastal placement use separate coordinate systems."""

import shutil
from copy import deepcopy

import pytest

from tests.test_spline_network import FIXTURE, geography_files, locators, network
from vic3_state_merger.splines import Anchor, Geography, SplineNetwork
from vic3_state_merger.splines.geography import build_geography
from vic3_state_merger.splines.merge import merge_spline_network
from vic3_state_merger.splines.network import (
    HUB_TYPES,
    NAVAL,
    NETWORK_PATH,
    Connection,
    Strip,
    connection_id,
)
from vic3_state_merger.state_merger import StateMerger

pytestmark = pytest.mark.unit


def port_case(tmp_path, inherited=True):
    # Top row: land. Bottom row: land, lake, sea, other sea.
    # The visual port is at z=1 (sea); the authored port is at z=1.25 (land).
    original = {
        "A": {"id": 1, "city": "x01", "provinces": ["x01"]},
        "SEA": {"id": 99, "provinces": ["x0000FF"]},
        "OTHER_SEA": {"id": 98, "provinces": ["x0000FE"]},
    }
    donor = "P" if inherited else "A"
    donor_id = 2 if inherited else 1
    original[donor] = {
        "id": donor_id,
        "city": "x01",
        "port": "x01",
        "provinces": ["x01"],
        "naval_exit_id": 99,
    }
    final = {"A": {**original[donor], "id": 1}}
    states = {**final, **{n: s for n, s in original.items() if "SEA" in n}}
    port, harbor = donor_id * 100 + 3, NAVAL | (donor_id * 100)
    points = {
        100: (0.5, 1.5),
        donor_id * 100: (0.5, 1.5),
        port: (2.25, 1.25),
        harbor: (2.5, 0.5),
        NAVAL | 9900: (2.75, 0.5),
        NAVAL | 9800: (3.5, 0.5),
    }
    routes = [
        (100, port, 1, ()),
        (harbor, NAVAL | 9900, 3, ()),
        (NAVAL | 9900, NAVAL | 9800, 2, ()),
    ]
    source = network(points, routes)
    visual = {**points, port: (2.25, 1.0)}
    old_locators = locators(original, visual)
    final_locators = locators(final, {100: visual[100], 103: visual[port]})
    files = geography_files(
        tmp_path,
        [1, 1, 1, 1, 1, 253, 255, 254],
        (4, 2),
        extra="lakes = { x0000FD }",
    )
    geo = build_geography(
        *files,
        states,
        tmp_path / "cache",
        sample_points=[*points.values(), visual[port], (1.5, 0.5)],
    )
    return [
        source,
        original,
        final,
        old_locators,
        final_locators,
        {"A": ["P"]} if inherited else {},
        geo,
    ]


@pytest.mark.parametrize("inherited", [False, True])
def test_coastal_locator_does_not_move_authored_port(tmp_path, inherited, spline_logs):
    args = port_case(tmp_path, inherited)
    before = deepcopy(args)
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert result.network.anchors[103] == Anchor(103, 2.25, 1.25)
    assert result.network.anchors[NAVAL | 100] == Anchor(NAVAL | 100, 2.5, 0.5)
    assert args[-1].province_at(2.25, 1.0) == 255
    assert args[-1].province_at(2.25, 1.25) == 1
    change = next(c for c in spline_logs("node_change") if c.get("hub") == "port")
    assert change["position"] == [2.25, 1.25]
    assert change["locator_position"] == [2.25, 1.0]
    assert change["coordinate_source"] == "donor_spline"
    assert change["donor"] == (203 if inherited else 103)
    assert args == before
    again = merge_spline_network(*args)
    assert (result.data, result.status) == (again.data, again.status)
    result.network.validate_references()


@pytest.mark.parametrize("hub", HUB_TYPES)
@pytest.mark.parametrize("inherited", [False, True])
def test_every_reused_hub_preserves_endpoint_and_route_geometry(
    hub, inherited, spline_logs
):
    suffix = HUB_TYPES.index(hub)
    donor_id = 2 if inherited else 1
    old_id = donor_id * 100 + suffix
    old = {"A": {"id": 1, "city": "x01"}}
    donor = "P" if inherited else "A"
    old[donor] = {**old.get(donor, {}), "id": donor_id, hub: "x02"}
    final = {"A": {"id": 1, "city": "x01", hub: "x02"}}
    # Only port placement needs a raster. API calls without it explicitly stay draft.
    if hub == "port":
        old["SEA"] = {"id": 99}
        old[donor]["naval_exit_id"] = final["A"]["naval_exit_id"] = 99
    points = {100: (1, 1), old_id: (2.25, 2.75)}
    source = network(points, [(100, old_id, 1, ())] if old_id != 100 else [])
    visual = {**points, old_id: (2.2, 2.8)}
    args = [
        source,
        old,
        final,
        locators(old, visual),
        locators(final, {100: visual[100], 100 + suffix: visual[old_id]}),
        {"A": ["P"]} if inherited else {},
        Geography(),
    ]
    result = merge_spline_network(*args)
    assert result.network.anchors[100 + suffix] == Anchor(100 + suffix, 2.25, 2.75)
    if hub == "port":
        assert "port_validation_unavailable" in {
            i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
        }
    if hub != "city":
        cid = connection_id(100, 100 + suffix, 1)
        assert cid in result.network.connections
        assert result.network.connections[cid].strips == (1,)
    for strip in result.network.strips.values():
        for anchor in strip.anchors:
            point = result.network.anchors[anchor]
            assert (point.x, point.z) in points.values()


@pytest.mark.parametrize(
    ("problem", "reason"),
    [
        ("wrong_province", "wrong_port_province"),
        ("owner", "wrong_port_owner"),
        ("inland", "not_coastal_land"),
        ("lake_side", "not_coastal_land"),
        ("outside", "out_of_bounds"),
    ],
)
def test_invalid_port_is_preserved_but_not_reused_for_reconstruction(
    spline_logs, tmp_path, problem, reason
):
    args = port_case(tmp_path)
    geo = args[-1]
    if problem == "wrong_province":
        args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    elif problem == "owner":
        geo.province_owners[1] = "another_state"
    elif problem in ("inland", "lake_side"):
        # A land province with only land/lake neighbors is not coastal.
        files = geography_files(
            tmp_path / problem,
            [1, 1, 1, 1, 1, 253, 253 if problem == "lake_side" else 1, 1],
            (4, 2),
            extra="lakes = { x0000FD }",
        )
        args[-1] = build_geography(
            *files,
            {**{n: s for n, s in args[1].items() if "SEA" in n}, **args[2]},
            tmp_path / problem / "cache",
            sample_points=[(2.25, 1.25)],
        )
        assert 1 not in args[-1].coastal_provinces
    else:
        args[0].anchors[203] = Anchor(203, -0.5, 1.25)
    # The invalid port also appears inside an otherwise reusable city-to-city path.
    args[1]["A"]["farm"] = args[2]["A"]["farm"] = "x01"
    args[3]["farm"] = args[4]["farm"] = {
        "game_object_locator": {"instances": [{"id": 1, "position": [0.75, 1.5]}]}
    }
    points = {i: (p.x, p.z) for i, p in args[0].anchors.items()}
    points[101] = (0.75, 1.5)
    args[0] = network(
        points,
        [
            (100, 101, 1, (203,)),
            (NAVAL | 200, NAVAL | 9900, 3, ()),
            (NAVAL | 9900, NAVAL | 9800, 2, ()),
        ],
    )
    result = merge_spline_network(*args)
    if problem == "owner":
        # No extra pixel-owner predicate was established by the accepted rules.
        assert result.status == "complete"
    else:
        kind = (
            "noncoastal_port_province"
            if problem in ("inland", "lake_side")
            else "invalid_port_placement"
        )
        issue = next(
            i
            for i in spline_logs("game_rule", "implementation", "unverified")
            if i["kind"] == kind
        )
        assert issue["reason"] == reason and issue["anchor"] == 103
        assert issue["category"] == "game_rule" and issue["expected_province"] == 1
        assert result.status == "draft"
    assert result.network.anchors[103] == Anchor(
        103, args[0].anchors[203].x, args[0].anchors[203].z
    )
    assert NAVAL | 100 in result.network.anchors
    assert set(result.network.connections) == {
        connection_id(100, 103, 1),
        connection_id(101, 103, 1),
        connection_id(NAVAL | 100, NAVAL | 9900, 3),
        connection_id(NAVAL | 9900, NAVAL | 9800, 2),
    }
    assert all(route["action"] == "preserve" for route in spline_logs("route"))
    assert not any(c["action"] == "demote" for c in spline_logs("node_change"))
    result.network.validate_references()


@pytest.mark.parametrize(
    ("position", "reason"),
    [
        ((2.5, 1.5), "not_sea"),
        ((1.5, 0.5), "not_sea"),
        ((3.5, 0.5), "wrong_sea_region"),
        ((4.5, 0.5), "out_of_bounds"),
    ],
)
def test_harbor_pixels_do_not_reject_authored_geometry(
    tmp_path, position, reason, spline_logs
):
    args = port_case(tmp_path)
    args[0].anchors[NAVAL | 200] = Anchor(NAVAL | 200, *position)
    result = merge_spline_network(*args)
    assert result.network.anchors[NAVAL | 100] == Anchor(NAVAL | 100, *position)
    assert 103 in result.network.anchors
    assert connection_id(100, 103, 1) in result.network.connections
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) in result.network.connections
    assert connection_id(NAVAL | 9900, NAVAL | 9800, 2) in result.network.connections
    assert (
        result.status == "complete"
        and spline_logs("game_rule", "implementation", "unverified") == []
    )
    assert not any(
        "placement" in i["kind"] for i in spline_logs("reconstruction", "advisory")
    )
    result.network.validate_references()


def test_missing_harbor_is_not_created_at_visual_port(tmp_path, spline_logs):
    args = port_case(tmp_path)
    args[0].anchors.pop(NAVAL | 200)
    result = merge_spline_network(*args)
    assert 103 in result.network.anchors and NAVAL | 100 not in result.network.anchors
    assert {"missing_harbor_geometry", "missing_harbor_connection"} <= {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }
    result.network.validate_references()


@pytest.mark.parametrize("problem", ["moved", "missing_source", "missing_donor"])
def test_created_ports_use_locator_coordinates_without_inventing_harbors(
    spline_logs, tmp_path, problem
):
    args = port_case(tmp_path)
    final_row = args[4]["port"]["game_object_locator"]["instances"][0]
    final_row["position"] = [2.25, 1.75]
    if problem == "missing_source":
        args[0].anchors.pop(203)
        args[3]["port"]["game_object_locator"]["instances"][0]["position"] = [
            2.25,
            1.75,
        ]
    elif problem == "missing_donor":
        args[1]["P"]["port"] = "x02"
    result = merge_spline_network(*args)
    assert result.network.anchors[103] == Anchor(103, 2.25, 1.75)
    assert NAVAL | 100 not in result.network.anchors
    assert connection_id(100, 103, 1) not in result.network.connections
    change = next(c for c in spline_logs("node_change") if c.get("hub") == "port")
    assert change["coordinate_source"] == "locator" and change["action"] == "create"
    assert {
        "moved": "moved_locator",
        "missing_source": "missing_source_hub",
        "missing_donor": "missing_hub_donor",
    }[problem] in {i["kind"] for i in spline_logs("reconstruction", "advisory")}
    assert result.status == "draft"
    result.network.validate_references()


def test_sub_tolerance_locator_change_keeps_donor_spline_coordinates(tmp_path):
    args = port_case(tmp_path)
    args[4]["port"]["game_object_locator"]["instances"][0]["position"] = [2.255, 1.0]
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert result.network.anchors[103] == Anchor(103, 2.25, 1.25)


@pytest.mark.parametrize("missing", ["all", "port", "harbor"])
def test_unavailable_samples_report_draft_without_moving_donors(
    tmp_path, missing, spline_logs
):
    args = port_case(tmp_path)
    geo = args[-1]
    if missing == "all":
        args[-1] = Geography()
    else:
        geo.province_samples.pop(
            geo.pixel_at(2.25, 1.25) if missing == "port" else geo.pixel_at(2.5, 0.5)
        )
    result = merge_spline_network(*args)
    assert result.status == ("complete" if missing == "harbor" else "draft")
    unverified = [
        i
        for i in spline_logs("game_rule", "implementation", "unverified")
        if i["kind"] == "port_validation_unavailable"
    ]
    if missing == "harbor":
        assert not unverified
    else:
        assert unverified[0]["category"] == "unverified"
    assert result.network.anchors[103] == Anchor(103, 2.25, 1.25)
    assert result.network.anchors[NAVAL | 100] == Anchor(NAVAL | 100, 2.5, 0.5)


def test_sampling_edges_lakes_corner_contact_and_cached_boundaries(tmp_path):
    files = geography_files(
        tmp_path, [1, 253, 2, 255], (2, 2), extra="lakes = { x0000FD }"
    )
    points = [(0, 2), (1, 1), (1.99, 0.01), (2, 1), (-0.01, 1), (0, 0), (0, 2.01)]
    geo = build_geography(*files, {}, tmp_path / "cache", sample_points=points)
    assert geo.province_at(0, 2) == 1
    assert geo.province_at(1.99, 0.01) == 255
    assert all(geo.province_at(*p) is None for p in points[3:])
    assert geo.coastal_provinces == {2}  # Province 1 touches sea only at a corner.
    assert geo.sea_provinces == {255} and geo.lake_provinces == {253}
    assert len(geo.province_samples) == 2
    cached = build_geography(*files, {}, tmp_path / "cache", sample_points=[(1, 2)])
    assert cached.province_at(1, 2) == 253  # Samples are not stale cached data.
    geo.wrap_x = True
    assert geo.province_at(2, 2) == 1
    assert geo.province_at(-0.01, 1) == 255
    assert geo.province_at(float("nan"), 1) is None
    assert Geography().province_at(0, 1) is None


@pytest.mark.integration
@pytest.mark.parametrize("problem", [None, "port", "harbor"])
def test_pipeline_serializes_donor_position_across_coastline(
    tmp_path, problem, spline_logs
):
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    port, harbor = (2, 2), (2, 0.5)
    if problem:
        source = SplineNetwork.from_bytes((game / NETWORK_PATH).read_bytes())
        if problem == "port":
            port = (2, 0.5)
            source.anchors[203] = Anchor(203, *port)
        else:
            harbor = (2, 2)
            source.anchors[NAVAL | 200] = Anchor(NAVAL | 200, *harbor)
        (game / NETWORK_PATH).write_bytes(source.to_bytes())
    merger = StateMerger(
        game, tmp_path / "mod", {"STATE_ALPHA": ["STATE_BETA"]}, tmp_path / "data"
    )
    merger.run(["spline_network"])
    result = merger.spline_result
    assert result is not None
    assert result.status == ("draft" if problem == "port" else "complete")
    parsed = SplineNetwork.from_bytes((tmp_path / "mod" / NETWORK_PATH).read_bytes())
    assert parsed.anchors[103] == Anchor(103, *port)
    assert parsed.anchors[NAVAL | 100] == Anchor(NAVAL | 100, *harbor)
    assert not (tmp_path / "data/spline-report.json").exists()
    change = next(c for c in spline_logs("node_change") if c.get("hub") == "port")
    assert change["position"] == list(port) and change["locator_position"] == [2, 1]
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) in parsed.connections
    if problem == "port":
        assert "invalid_port_placement" in {
            i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
        }
    else:
        assert spline_logs("game_rule", "implementation", "unverified") == []


@pytest.mark.integration
@pytest.mark.parametrize("anchor_present", [False, True])
def test_pipeline_preserves_unplaced_mine_policy_after_donor_rename(
    tmp_path, anchor_present, spline_logs
):
    game = tmp_path / "game"
    shutil.copytree(FIXTURE, game)
    (
        game / "gfx/map/map_object_data/generated_map_object_locators_mine.txt"
    ).write_text(
        "game_object_locator = { instances = { { id = 2 position = { -1 0 -1 } } } }"
    )
    if not anchor_present:
        source = SplineNetwork.from_bytes((game / NETWORK_PATH).read_bytes())
        for identity, conn in list(source.connections.items()):
            if 202 in source.connection_path(conn):
                del source.connections[identity]
                for strip in conn.strips:
                    del source.strips[strip]
        del source.anchors[202]
        # The toy input's road bypasses its intentionally absent mine hub.
        source.strips[2049] = Strip(2049, (200, 203))
        identity = connection_id(200, 203, 1)
        source.connections[identity] = Connection(identity, (2049,))
        source.validate_references()
        (game / NETWORK_PATH).write_bytes(source.to_bytes())
    before = {p: p.read_bytes() for p in game.rglob("*") if p.is_file()}
    merger = StateMerger(
        game, tmp_path / "mod", {"STATE_ALPHA": ["STATE_BETA"]}, tmp_path / "data"
    )
    merger.run(["spline_network"])
    assert merger.spline_result is not None
    assert merger.spline_result.status == "complete"
    emitted = SplineNetwork.from_bytes((tmp_path / "mod" / NETWORK_PATH).read_bytes())
    emitted.validate_references()
    assert (102 in emitted.anchors) == anchor_present
    assert 202 not in emitted.anchors
    if anchor_present:
        assert emitted.anchors[102] == Anchor(102, 2, 2)
        assert not any(
            i["kind"] == "unplaced_hub_skipped" for i in spline_logs("not_applicable")
        )
    else:
        assert [
            i["anchor"]
            for i in spline_logs("not_applicable")
            if i["kind"] == "unplaced_hub_skipped"
        ] == [102]
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert all(p.read_bytes() == data for p, data in before.items())
