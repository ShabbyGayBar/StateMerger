# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Passable land adjacency creates obligations; straits only permit crossings."""

from copy import deepcopy

import pytest

from tests.test_spline_network import geography_files, network
from tests.test_spline_placement import port_case
from tests.test_spline_validation import land_case
from vic3_state_merger.splines import Anchor, Geography
from vic3_state_merger.splines.geography import build_geography
from vic3_state_merger.splines.merge import merge_spline_network
from vic3_state_merger.splines.network import NAVAL, connection_id

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("pixels", [[1, 2], [1, 255, 2]])
@pytest.mark.parametrize("road", [False, True])
def test_strait_permits_a_road_but_never_requires_one(
    tmp_path, pixels, road, spline_logs
):
    args = land_case([(100, 200, 1, ())] if road else [], farm=False)
    for name, province in (("A", "x01"), ("B", "x02")):
        args[1][name]["provinces"] = [province]
    files = geography_files(
        tmp_path, pixels, (len(pixels), 1), csv="x01;x02;sea;-1;strait\n"
    )
    geo = build_geography(*files, args[2], tmp_path / "cache")
    args[-1] = geo
    assert geo.required == {}
    assert geo.straits[("A", "B")]
    assert geo.adjacent("A", "B") is True
    assert geo.land_connections_required("A") is False
    before = deepcopy(args)
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert result.network.connections == args[0].connections
    assert all(r["action"] == "preserve" for r in spline_logs("route"))
    assert {i["state"] for i in spline_logs("not_applicable")} == {"A", "B"}
    assert args == before


@pytest.mark.parametrize("road", [False, True])
def test_another_land_border_still_requires_a_link_despite_a_strait(
    tmp_path, road, spline_logs
):
    args = land_case([(100, 200, 1, ())] if road else [], farm=False)
    args[1]["A"]["provinces"] = ["x01", "x03"]
    args[1]["B"]["provinces"] = ["x02"]
    files = geography_files(tmp_path, [1, 2, 3], (3, 1), csv="x01;x02;sea;-1;strait\n")
    args[-1] = build_geography(*files, args[2], tmp_path / "cache")
    assert ("A", "B") in args[-1].required
    assert ("A", "B") in args[-1].straits
    assert args[-1].land_connections_required("A") is True
    result = merge_spline_network(*args)
    assert result.status == ("complete" if road else "draft")
    if not road:
        assert "unconnected_state" in {i["kind"] for i in spline_logs("game_rule")}
        assert "missing_state_connection" in {
            i["kind"] for i in spline_logs("advisory")
        }
    assert spline_logs("not_applicable") == []


@pytest.mark.parametrize("blocker", ["province", "crossing"])
def test_mainland_without_passable_neighbors_has_no_land_obligation(
    tmp_path, blocker, spline_logs
):
    args = land_case([], farm=True)
    args[1]["A"]["provinces"] = ["x01"]
    args[1]["B"]["provinces"] = ["x02"]
    if blocker == "province":
        args[1]["A"]["impassable"] = ["x01"]
    files = geography_files(
        tmp_path,
        [1, 2],
        (2, 1),
        csv="x01;x02;impassable;-1;blocked\n" if blocker == "crossing" else "",
    )
    args[-1] = build_geography(*files, args[2], tmp_path / "cache")
    assert args[-1].blocked and not args[-1].required
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert spline_logs("game_rule", "implementation", "unverified") == []
    assert "optional_internal_connectivity_gap" in {
        i["kind"] for i in spline_logs("reconstruction")
    }
    assert "disconnected_state_hubs" not in {
        i["kind"] for i in spline_logs("reconstruction")
    }


@pytest.mark.parametrize("kind", ["sea", "strait"])
def test_manual_strait_evidence_is_normalized_without_editing_caller_data(kind):
    supplied = {("A", "B"): [{"kind": kind}]}
    before = deepcopy(supplied)
    geo = Geography(required=supplied)
    assert geo.required == {} and geo.straits[("A", "B")][0]["kind"] == "strait"
    assert geo.adjacent("A", "B") is True
    assert geo.land_connections_required("A") is False
    assert supplied == before


@pytest.mark.parametrize("evidence", [[], [{"kind": "land"}, {"kind": "strait"}]])
def test_manual_required_pair_stays_required_with_optional_strait(
    evidence, spline_logs
):
    args = land_case([], farm=False)
    args[-1] = Geography(
        required={("A", "B"): evidence}, straits={("A", "B"): [{"kind": "strait"}]}
    )
    assert args[-1].land_connections_required("A") is True
    assert merge_spline_network(*args).status == "draft"
    assert "missing_state_connection" in {i["kind"] for i in spline_logs("advisory")}
    assert "unconnected_state" in {i["kind"] for i in spline_logs("game_rule")}


def test_impassable_province_still_blocks_an_explicit_strait(tmp_path, spline_logs):
    args = land_case([(100, 200, 1, ())], farm=False)
    args[1]["A"].update(provinces=["x01"], impassable=["x01"])
    args[1]["B"]["provinces"] = ["x02"]
    files = geography_files(tmp_path, [1, 2], (2, 1), csv="x01;x02;sea;-1;strait\n")
    args[-1] = build_geography(*files, args[2], tmp_path / "cache")
    assert args[-1].required == {} and args[-1].straits == {}
    assert args[-1].adjacent("A", "B") is False
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert "nonadjacent_state_connection" in {
        i["kind"] for i in spline_logs("game_rule")
    }
    assert result.network.connections == args[0].connections


def test_strait_permission_does_not_resolve_an_unknown_land_requirement(
    tmp_path, spline_logs
):
    args = land_case([(100, 200, 1, ())])
    args[1]["A"]["provinces"] = ["x01", "x03"]
    args[1]["B"]["provinces"] = ["x02"]
    files = geography_files(
        tmp_path,
        [1, 255, 2, 255, 3],
        (5, 1),
        csv="x01;x02;sea;-1;strait\nx03;x02;special;-1;unknown\n",
    )
    args[-1] = build_geography(*files, args[2], tmp_path / "cache")
    assert args[-1].adjacent("A", "B") is True
    assert args[-1].land_connections_required("A") is None
    assert merge_spline_network(*args).status == "draft"
    assert "unknown_adjacency_type" in {i["kind"] for i in spline_logs("unverified")}
    assert spline_logs("game_rule") == []
    assert spline_logs("not_applicable") == []


@pytest.mark.parametrize("unknown", ["global", "pair"])
def test_uncertain_land_adjacency_cannot_grant_an_exemption(unknown, spline_logs):
    args = land_case([], farm=True)
    args[-1] = Geography(
        adjacency_available=unknown != "global",
        uncertain={("A", "B"): [{"kind": "special"}]} if unknown == "pair" else {},
        straits={("A", "B"): [{"kind": "strait"}]},
    )
    assert args[-1].adjacent("A", "B") is True
    assert args[-1].land_connections_required("A") is None
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert spline_logs("game_rule", "implementation") == []
    assert "unconnected_state" in {i["kind"] for i in spline_logs("unverified")}
    groups = [
        i for i in spline_logs("advisory") if i["kind"] == "disconnected_state_hubs"
    ]
    assert len(groups) == 1 and groups[0]["unverified"] is True
    assert spline_logs("not_applicable") == []


def test_known_land_neighbor_enables_checks_despite_unknown_other_neighbors(
    spline_logs,
):
    args = land_case([], farm=True)
    args[-1].adjacency_available = False
    args[-1].uncertain[("A", "C")] = [{"kind": "special"}]
    assert args[-1].land_connections_required("A") is True
    assert merge_spline_network(*args).status == "draft"
    assert "unconnected_state" in {i["kind"] for i in spline_logs("game_rule")}
    groups = [
        i for i in spline_logs("advisory") if i["kind"] == "disconnected_state_hubs"
    ]
    assert len(groups) == 1 and groups[0]["unverified"] is False


def test_optional_internal_routes_can_still_be_assembled_from_authored_paths(
    spline_logs,
):
    args = land_case([], required=())
    del args[1]["B"]
    args[1]["DONOR"] = {"id": 3, "city": "x03"}
    args[2] = {"A": args[1]["A"]}
    args[5] = {"A": ["DONOR"]}
    args[3]["city"]["game_object_locator"]["instances"] = [
        {"id": 1, "position": [0, 1]},
        {"id": 3, "position": [2, 1]},
    ]
    args[4] = deepcopy(args[3])
    args[4]["city"]["game_object_locator"]["instances"] = [
        {"id": 1, "position": [0, 1]}
    ]
    args[0] = network(
        {100: (0, 1), 101: (1, 1), 300: (2, 1)}, [(100, 300, 1, ()), (300, 101, 1, ())]
    )
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert connection_id(100, 101, 1) in result.network.connections
    assert spline_logs("route")[0]["action"] == "assemble"


@pytest.mark.parametrize(
    "problem", ["hub", "port", "harbor", "naval_exit", "route_type"]
)
def test_land_exemption_does_not_waive_independent_checks(
    tmp_path, problem, spline_logs
):
    args = port_case(tmp_path)
    assert args[-1].land_connections_required("A") is False
    if problem == "hub":
        args[4]["city"]["game_object_locator"]["instances"].clear()
        args[0].anchors.pop(100)
    elif problem == "port":
        args[0].anchors[203] = Anchor(203, 2.25, 0.5)
    elif problem == "harbor":
        args[0].anchors.pop(NAVAL | 200)
    elif problem == "naval_exit":
        args[2]["A"]["naval_exit_id"] = 1
    else:
        # A known naval route with a land anchor remains invalid on an exempt state.
        from vic3_state_merger.splines.network import Strip

        cid = connection_id(100, 203, 1)
        sid = args[0].connections[cid].strips[0]
        args[0].anchors[NAVAL | 10] = Anchor(NAVAL | 10, 1, 1)
        args[0].strips[sid] = Strip(sid, (100, NAVAL | 10, 203))
    result = merge_spline_network(*args)
    assert result.status == "draft"
    expected = {
        "hub": "locator_validation_unavailable",
        "port": "invalid_port_placement",
        "harbor": "missing_harbor_geometry",
        "naval_exit": "invalid_naval_exit",
        "route_type": "incompatible_anchor_type",
    }[problem]
    assert expected in {i["kind"] for i in spline_logs("game_rule", "unverified")}
