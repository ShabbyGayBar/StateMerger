# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Final-network rules and reconstruction eligibility are independent contracts."""

from copy import deepcopy
from typing import Any

import pytest

from tests.test_spline_network import chain_case, geography_files, locators, network
from tests.test_spline_placement import port_case
from vic3_state_merger.splines import Anchor, Geography
from vic3_state_merger.splines.geography import build_geography
from vic3_state_merger.splines.merge import locator_positions, merge_spline_network
from vic3_state_merger.splines.network import NAVAL, Connection, Strip, connection_id

pytestmark = pytest.mark.unit


def land_case(routes, *, farm=True, required=(("A", "B"),)):
    states = {"A": {"id": 1, "city": "x01"}, "B": {"id": 2, "city": "x02"}}
    points = {100: (0, 1), 200: (3, 1)}
    if farm:
        states["A"]["farm"] = "x01"
        points[101] = (1, 1)
    tables = locators(states, points)
    return [
        network(points, routes),
        states,
        states,
        tables,
        tables,
        {},
        Geography(required={pair: [{"kind": "land"}] for pair in required}),
    ]


def test_absent_hub_with_unplaced_locator_is_not_applicable(spline_logs):
    args = land_case([(100, 200, 1, ())])
    args[0].anchors.pop(101)
    args[4]["farm"]["game_object_locator"]["instances"][0]["position"] = [-1, 0, -1]
    before = deepcopy(args)
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert [
        i["anchor"]
        for i in spline_logs("not_applicable")
        if i["kind"] == "unplaced_hub_skipped"
    ] == [101]
    assert 101 not in result.network.anchors
    assert result.network.connections == args[0].connections
    assert args == before
    assert merge_spline_network(*args).data == result.data


def test_unplaced_locator_does_not_hide_an_existing_disconnected_anchor(spline_logs):
    args = land_case([(100, 200, 1, ())])
    args[4]["farm"]["game_object_locator"]["instances"][0]["position"] = [-1, 0, -1]
    result = merge_spline_network(*args)
    assert (
        result.status == "complete"
        and result.network.anchors[101] == args[0].anchors[101]
    )
    assert "disconnected_state_hubs" in {i["kind"] for i in spline_logs("advisory")}
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert not any(
        i["kind"] == "unplaced_hub_skipped" for i in spline_logs("not_applicable")
    )


@pytest.mark.parametrize("missing", ["table", "entry"])
@pytest.mark.parametrize("anchor_present", [False, True])
def test_missing_locator_data_is_unverified_not_an_inactive_hub(
    missing, anchor_present, spline_logs
):
    args = land_case(
        [(100, 101, 1, ()), (101, 200, 1, ())]
        if anchor_present
        else [(100, 200, 1, ())]
    )
    if not anchor_present:
        args[0].anchors.pop(101)
    if missing == "table":
        del args[4]["farm"]
    else:
        args[4]["farm"]["game_object_locator"]["instances"].clear()
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert (101 in result.network.anchors) == anchor_present
    findings = spline_logs("game_rule", "implementation", "unverified")
    assert [(i["kind"], i["category"], i["anchor"]) for i in findings] == [
        ("locator_validation_unavailable", "unverified", 101)
    ]
    assert not any(
        i["kind"] == "unplaced_hub_skipped" for i in spline_logs("not_applicable")
    )


def test_direct_validation_without_locator_data_is_unverified(spline_logs):
    from vic3_state_merger.splines.validation import validate_final_network

    args = land_case([(100, 101, 1, ()), (101, 200, 1, ())])
    before = deepcopy(args[0])
    assert not validate_final_network(args[0], args[2], args[-1])
    findings = spline_logs("game_rule", "implementation", "unverified")
    assert len(findings) == 3
    assert all(i["kind"] == "locator_validation_unavailable" for i in findings)
    assert all(i["category"] == "unverified" for i in findings)
    assert args[0] == before


@pytest.mark.parametrize("position", [(1, 1), (-1, 0), (0, -1)])
def test_only_the_exact_unplaced_sentinel_exempts_an_absent_hub(position, spline_logs):
    from vic3_state_merger.splines.validation import validate_final_network

    args = land_case([(100, 200, 1, ())])
    args[0].anchors.pop(101)
    positions = locator_positions(args[4])
    positions["farm"][1] = position
    assert not validate_final_network(args[0], args[2], args[-1], locators=positions)
    assert [(i["kind"], i["anchor"]) for i in spline_logs("game_rule")] == [
        ("missing_required_hub", 101)
    ]
    assert not any(
        i["kind"] == "unplaced_hub_skipped" for i in spline_logs("not_applicable")
    )


@pytest.mark.parametrize(
    "problem", [None, "coast", "coast_unverified", "harbor", "sea", "exit", "route"]
)
def test_unplaced_missing_port_does_not_waive_naval_requirements(
    tmp_path, problem, spline_logs
):
    args = port_case(tmp_path)
    args[0].anchors.pop(203)
    args[0].connections.pop(connection_id(100, 203, 1))
    # Keep the active land hubs connected independently of the inactive port.
    args[1]["A"]["farm"] = args[2]["A"]["farm"] = "x01"
    args[3]["farm"] = args[4]["farm"] = {
        "game_object_locator": {"instances": [{"id": 1, "position": [0.75, 1.5]}]}
    }
    args[0].anchors[101] = Anchor(101, 0.75, 1.5)
    args[0].strips[769] = Strip(769, (100, 101))
    cid = connection_id(100, 101, 1)
    args[0].connections[cid] = Connection(cid, (769,))
    args[4]["port"]["game_object_locator"]["instances"][0]["position"] = [-1, 0, -1]
    if problem == "harbor":
        args[0].anchors.pop(NAVAL | 200)
    elif problem == "coast":
        args[-1].coastal_provinces.clear()
    elif problem == "coast_unverified":
        args[-1].placement_available = False
    elif problem == "sea":
        args[0].anchors.pop(NAVAL | 9900)
    elif problem == "exit":
        args[2]["A"]["naval_exit_id"] = 1
    elif problem == "route":
        args[0].connections.pop(connection_id(NAVAL | 200, NAVAL | 9900, 3))
    result = merge_spline_network(*args)
    assert 103 not in result.network.anchors
    assert [
        i["anchor"]
        for i in spline_logs("not_applicable")
        if i["kind"] == "unplaced_hub_skipped"
    ] == [103]
    findings = spline_logs("game_rule", "implementation", "unverified")
    assert "missing_required_hub" not in {i["kind"] for i in findings}
    if problem is None:
        assert result.status == "complete" and findings == []
    else:
        assert result.status == "draft"
        expected = {
            "coast": "noncoastal_port_province",
            "coast_unverified": "port_validation_unavailable",
            "harbor": "missing_harbor_geometry",
            "sea": "missing_sea_hub",
            "exit": "invalid_naval_exit",
            "route": "missing_harbor_connection",
        }[problem]
        assert expected in {i["kind"] for i in findings}
        if problem == "coast_unverified":
            assert findings[0]["category"] == "unverified"
            assert findings[0]["checks"] == ["coastal_port_province"]
    if problem != "harbor":
        assert NAVAL | 100 in result.network.anchors
    result.network.validate_references()


def test_unplaced_existing_port_still_gets_placement_checks(tmp_path, spline_logs):
    args = port_case(tmp_path)
    args[4]["port"]["game_object_locator"]["instances"][0]["position"] = [-1, 0, -1]
    args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    result = merge_spline_network(*args)
    assert result.network.anchors[103] == Anchor(103, 2.25, 0.5)
    assert result.status == "draft"
    assert "invalid_port_placement" in {i["kind"] for i in spline_logs("game_rule")}
    assert not any(
        i["kind"] == "unplaced_hub_skipped" for i in spline_logs("not_applicable")
    )


def test_global_land_path_may_detour_through_a_neighbor(spline_logs):
    args = land_case([(100, 200, 1, ()), (200, 101, 1, ())])
    before = deepcopy(args)
    result = merge_spline_network(*args)
    assert (
        result.status == "complete"
        and spline_logs("game_rule", "implementation", "unverified") == []
    )
    # The internal construction attempt failed, but final global connectivity passes.
    assert "disconnected_state_hubs" in {
        i["kind"] for i in spline_logs("reconstruction", "advisory")
    }
    assert result.network.connections == args[0].connections
    assert set(result.network.anchors) == {
        100,
        101,
        200,
    }  # Only declared hubs required.
    assert args == before
    repeated = merge_spline_network(*args)
    assert (result.data, result.status) == (repeated.data, repeated.status)


def test_genuinely_disconnected_declared_hub_is_a_final_advisory(spline_logs, caplog):
    import logging

    result = merge_spline_network(*land_case([(100, 200, 1, ())]))
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    issue = next(
        i for i in spline_logs("advisory") if i["kind"] == "disconnected_state_hubs"
    )
    assert issue["category"] == "advisory"
    assert issue["scope"] == "global_land_network"
    assert issue["components"] == [[100], [101]]
    assert issue["unverified"] is False
    records = [
        record
        for record in caplog.records
        if record.name == "vic3_state_merger.splines.validation"
        and record.msg == "%s (%s): %s"
        and record.args[0] == "disconnected_state_hubs"
    ]
    assert len(records) == 1 and records[0].levelno == logging.WARNING


def test_indirect_global_path_does_not_replace_a_direct_adjacent_state_link(
    spline_logs,
    caplog,
):
    states = {n: {"id": i, "city": f"x0{i}"} for i, n in enumerate(("A", "B", "C"), 1)}
    points = {100: (1, 1), 200: (2, 1), 300: (3, 1)}
    source = network(points, [(100, 300, 1, ()), (300, 200, 1, ())])
    tables = locators(states, points)
    geo = Geography(
        required={
            pair: [{"kind": "land"}] for pair in (("A", "B"), ("A", "C"), ("B", "C"))
        }
    )
    before = deepcopy((source, states, tables, geo))
    result = merge_spline_network(source, states, states, tables, tables, {}, geo)
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert [
        (i["kind"], i["states"], i["crossing"], i["unverified"])
        for i in spline_logs("advisory")
    ] == [("missing_state_connection", ["A", "B"], {"kind": "land"}, False)]
    records = [
        r
        for r in caplog.records
        if r.name == "vic3_state_merger.splines.validation"
        and r.msg == "%s (%s): %s"
        and r.args[0] == "missing_state_connection"
    ]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert result.data == source.to_bytes()
    assert (source, states, tables, geo) == before
    repeated = merge_spline_network(source, states, states, tables, tables, {}, geo)
    assert (repeated.data, repeated.status) == (result.data, result.status)


def test_single_hub_without_passable_land_neighbors_has_no_land_obligation(spline_logs):
    states = {"A": {"id": 1, "city": "x01"}}
    points = {100: (1, 1)}
    tables = locators(states, points)
    result = merge_spline_network(
        network(points, []), states, states, tables, tables, {}, Geography()
    )
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert [i["kind"] for i in spline_logs("not_applicable")] == [
        "land_connectivity_not_applicable"
    ]


def test_unused_broken_source_records_do_not_make_valid_output_a_draft(spline_logs):
    args = land_case([(100, 101, 1, ()), (101, 200, 1, ())])
    args[0].strips[513] = Strip(513, (100, 9999))
    identity = connection_id(100, 9999, 1)
    args[0].connections[identity] = Connection(identity, (513,))
    before = deepcopy(args)
    result = merge_spline_network(*args)
    assert (
        result.status == "complete"
        and spline_logs("game_rule", "implementation", "unverified") == []
    )
    assert {i["kind"] for i in spline_logs("reconstruction", "advisory")} >= {
        "quarantined_strip",
        "quarantined_connection",
    }
    assert (
        identity not in result.network.connections and 513 not in result.network.strips
    )
    assert args == before
    result.network.validate_references()


def test_nonadjacent_authored_route_is_preserved_and_reported(spline_logs):
    args = land_case([(100, 200, 1, ())], farm=False, required=())
    result = merge_spline_network(*args, repair_splines=False)
    assert result.network.connections == args[0].connections
    assert result.network.strips == args[0].strips
    issue = next(
        i
        for i in spline_logs("game_rule", "implementation", "unverified")
        if i["kind"] == "nonadjacent_state_connection"
    )
    assert issue["category"] == "game_rule" and issue["states"] == ["A", "B"]
    assert all(r["action"] == "preserve" for r in spline_logs("route"))


def test_mixed_type_crossing_cannot_seed_a_new_route(spline_logs):
    args: list[Any] = list(chain_case())
    source = args[0]
    source.anchors[NAVAL | 10] = Anchor(NAVAL | 10, 2, 1)
    identity = connection_id(200, 400, 0)
    strip = source.connections[identity].strips[0]
    source.strips[strip] = Strip(strip, (200, NAVAL | 10, 400))
    result = merge_spline_network(*args)
    assert not result.network.connections
    assert "missing_state_connection" in {i["kind"] for i in spline_logs("advisory")}
    assert not any(identity in r["source_connections"] for r in spline_logs("route"))


def test_mixed_type_authored_route_is_preserved_and_reported(spline_logs):
    args = land_case([(100, 200, 1, (NAVAL | 10,))], farm=False)
    args[0].anchors[NAVAL | 10] = Anchor(NAVAL | 10, 1, 1)
    result = merge_spline_network(*args, repair_splines=False)
    assert result.network.connections == args[0].connections
    path = result.network.strips[1].anchors
    assert path[0] == 100 and path[-1] == 200
    assert [
        (result.network.anchors[n].x, result.network.anchors[n].z) for n in path
    ] == [(0, 1), (1, 1), (3, 1)]
    assert "incompatible_anchor_type" in {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }


def test_unknown_route_type_is_preserved_with_unverified_checks(spline_logs):
    args = land_case([(100, 200, 5, ())], farm=False)
    result = merge_spline_network(*args)
    assert result.data == args[0].to_bytes()
    assert result.status == "draft"
    assert "unsupported_spline_type" in {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }
    assert all(
        i["category"] == "unverified"
        for i in spline_logs("game_rule", "implementation", "unverified")
    )
    direct = [
        i for i in spline_logs("advisory") if i["kind"] == "missing_state_connection"
    ]
    assert len(direct) == 1 and direct[0]["unverified"] is True


def test_unknown_type_does_not_infer_traffic_rules_from_intermediate_geometry(
    spline_logs,
):
    args = land_case([(100, 200, 5, (NAVAL | 10,))], farm=False)
    args[0].anchors[NAVAL | 10] = Anchor(NAVAL | 10, 1, 1)
    result = merge_spline_network(*args)
    assert result.network.connections == args[0].connections
    assert result.status == "draft"
    assert all(
        i["category"] == "unverified"
        for i in spline_logs("game_rule", "implementation", "unverified")
    )


@pytest.mark.parametrize("available", [True, False])
def test_unknown_adjacency_is_not_reported_as_confirmed_nonadjacency(
    spline_logs, tmp_path, available
):
    args = land_case([(100, 200, 1, ())], farm=False)
    if available:
        states = {
            "A": {"id": 1, "city": "x01", "provinces": ["x01"]},
            "B": {"id": 2, "city": "x02", "provinces": ["x02"]},
        }
        files = geography_files(
            tmp_path, [1, 2], (2, 1), csv="x01;x02;special;-1;unknown\n"
        )
        args[-1] = build_geography(*files, states, tmp_path / "cache")
        assert ("A", "B") not in args[-1].required
    else:
        args[-1] = Geography(adjacency_available=False)
    assert args[-1].adjacent("A", "B") is None
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert all(
        i["category"] == "unverified"
        for i in spline_logs("game_rule", "implementation", "unverified")
    )
    assert "nonadjacent_state_connection" not in {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }
    assert result.network.connections == args[0].connections


def test_known_alternative_border_can_establish_adjacency_despite_unknown_crossing(
    spline_logs,
    tmp_path,
):
    args = land_case([(100, 200, 1, ())], farm=False)
    states = {
        "A": {"id": 1, "city": "x01", "provinces": ["x01", "x03"]},
        "B": {"id": 2, "city": "x02", "provinces": ["x02"]},
    }
    files = geography_files(
        tmp_path, [1, 2, 3], (3, 1), csv="x01;x02;special;-1;unknown\n"
    )
    args[-1] = build_geography(*files, states, tmp_path / "cache")
    assert args[-1].adjacent("A", "B") is True
    result = merge_spline_network(*args)
    assert (
        result.status == "complete"
        and spline_logs("game_rule", "implementation", "unverified") == []
    )
    assert "unknown_adjacency_type" in {
        i["kind"] for i in spline_logs("reconstruction", "advisory")
    }


def test_harbor_route_to_other_sea_is_only_advisory(tmp_path, spline_logs):
    args = port_case(tmp_path)
    args[2]["A"]["naval_exit_id"] = 98
    result = merge_spline_network(*args)
    assert (
        result.status == "complete"
        and spline_logs("game_rule", "implementation", "unverified") == []
    )
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) in result.network.connections
    assert [i["kind"] for i in spline_logs("reconstruction", "advisory")] == [
        "harbor_naval_exit_mismatch"
    ]
    assert spline_logs("reconstruction", "advisory")[0]["connected_seas"] == [
        NAVAL | 9900
    ]


@pytest.mark.parametrize(
    "problem",
    [
        "invalid_region",
        "undefined_region",
        "missing_sea",
        "missing_harbor",
        "missing_route",
    ],
)
def test_naval_failures_are_distinguished(tmp_path, problem, spline_logs):
    args = port_case(tmp_path)
    if problem == "invalid_region":
        args[2]["A"]["naval_exit_id"] = 1  # Land state, not a sea region.
    elif problem == "undefined_region":
        args[2]["A"]["naval_exit_id"] = 999999  # No packed sea ID should be allocated.
    elif problem == "missing_sea":
        args[0].anchors.pop(NAVAL | 9900)
    elif problem == "missing_harbor":
        args[0].anchors.pop(NAVAL | 200)
    else:
        args[0].connections.pop(connection_id(NAVAL | 200, NAVAL | 9900, 3))
    result = merge_spline_network(*args)
    kinds = {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }
    assert result.status == "draft"
    expected = {
        "invalid_region": "invalid_naval_exit",
        "undefined_region": "invalid_naval_exit",
        "missing_sea": "missing_sea_hub",
        "missing_harbor": "missing_harbor_geometry",
        "missing_route": "missing_harbor_connection",
    }[problem]
    assert expected in kinds
    if problem not in ("invalid_region", "undefined_region"):
        assert "invalid_naval_exit" not in kinds
    if problem != "missing_sea":
        assert "missing_sea_hub" not in kinds
    if problem != "missing_harbor":
        assert "missing_harbor_geometry" not in kinds
    result.network.validate_references()


@pytest.mark.parametrize("exit_id", [-1, 99])
def test_explicit_naval_exit_is_checked_without_imposing_a_port_declaration(
    exit_id, spline_logs
):
    args = land_case([(100, 200, 1, ())], farm=False)
    args[1]["A"]["naval_exit_id"] = exit_id
    args[1]["SEA"] = {"id": 99}
    result = merge_spline_network(*args)
    if exit_id == -1:
        assert (
            result.status == "complete"
            and spline_logs("game_rule", "implementation", "unverified") == []
        )
    else:
        assert [
            i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
        ] == ["missing_sea_hub"]
    assert "missing_harbor_geometry" not in {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }


def test_port_validation_uses_emitted_float32_coordinates(tmp_path, spline_logs):
    args = port_case(tmp_path)
    args[0].anchors[203] = Anchor(203, 1.99999999, 1.25)
    args[-1].province_samples[(1, 0)] = 1
    args[-1].province_samples[(2, 0)] = 255
    result = merge_spline_network(*args)
    issue = next(
        i
        for i in spline_logs("game_rule", "implementation", "unverified")
        if i["kind"] == "invalid_port_placement"
    )
    assert issue["position"] == [2.0, 1.25]
    assert issue["sampled_province"] == 255 and result.status == "draft"
    assert all(r["action"] == "preserve" for r in spline_logs("route"))


@pytest.mark.parametrize(
    ("category", "event", "level"),
    [
        ("game_rule", "unconnected_state", "ERROR"),
        ("advisory", "missing_state_connection", "WARNING"),
        ("unverified", "unverified_state_connection", "WARNING"),
        ("implementation", "unknown_land_endpoint", "ERROR"),
    ],
)
def test_validation_log_severity_and_context(category, event, level, caplog):
    from vic3_state_merger.splines.validation import validate_final_network

    args = land_case([], farm=False)
    if category == "unverified":
        args = land_case([(100, 200, 1, ())], farm=False)
        args[-1] = Geography(adjacency_available=False)
    elif category == "implementation":
        args[0] = network({100: (0, 1), 900: (3, 1)}, [(100, 900, 1, ())])
    before = deepcopy(args[0])
    assert not validate_final_network(args[0], args[2], args[-1])
    finding = next(r for r in caplog.records if r.args and r.args[0] == event)
    assert finding.name == "vic3_state_merger.splines.validation"
    assert finding.levelname == level
    assert finding.args[1] == category
    if category == "advisory":
        assert finding.args[2]["states"] == ["A", "B"]
    elif category == "game_rule":
        assert finding.args[2]["state"] == "A"
    else:
        assert finding.args[2]["connection"] == next(iter(args[0].connections))
    assert args[0] == before


@pytest.mark.parametrize("mode", ["filtered", "disabled"])
@pytest.mark.parametrize(
    "status", ["complete", "advisory", "direct_advisory", "violation", "unverified"]
)
def test_status_does_not_depend_on_logging(
    mode, status, application_logging, monkeypatch
):
    from vic3_state_merger.logging_config import configure_logging

    args = land_case([(100, 101, 1, ()), (101, 200, 1, ())])
    if status == "violation":
        args[0].connections.pop(connection_id(101, 200, 1))
    elif status == "advisory":
        args[0].connections.pop(connection_id(100, 101, 1))
    elif status == "direct_advisory":
        args[1]["C"] = {"id": 3, "city": "x03"}
        points = {100: (0, 1), 101: (1, 1), 200: (3, 1), 300: (2, 1)}
        args[0] = network(
            points, [(100, 101, 1, ()), (100, 300, 1, ()), (300, 200, 1, ())]
        )
        args[3] = args[4] = locators(args[1], points)
        args[-1] = Geography(
            required={
                pair: [{"kind": "land"}]
                for pair in (("A", "B"), ("A", "C"), ("B", "C"))
            }
        )
    elif status == "unverified":
        args[-1] = Geography(adjacency_available=False)
    expected = merge_spline_network(*args)
    configure_logging("CRITICAL" if mode == "filtered" else "DEBUG", console=False)
    if mode == "disabled":
        import logging

        for name in ("merge", "validation"):
            monkeypatch.setattr(
                logging.getLogger(f"vic3_state_merger.splines.{name}"), "disabled", True
            )
    actual = merge_spline_network(*args)
    assert actual.status == (
        "complete" if status in {"complete", "advisory", "direct_advisory"} else "draft"
    )
    assert (actual.data, actual.status) == (expected.data, expected.status)
