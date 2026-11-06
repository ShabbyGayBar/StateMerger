# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Original synthetic spline fixtures: codec, topology and file boundaries."""

import math
import shutil
import struct
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from vic3_state_merger import cli, gui
from vic3_state_merger.sources import SourceResolver
from vic3_state_merger.splines.geography import Geography, build_geography, color_code
from vic3_state_merger.splines.merge import locator_positions, merge_spline_network
from vic3_state_merger.splines.network import (
    INTERMEDIATE,
    NAVAL,
    NETWORK_PATH,
    Anchor,
    Connection,
    SplineNetwork,
    Strip,
    anchor_id,
    connection_id,
    endpoints,
)
from vic3_state_merger.state_merger import StateMerger

pytestmark = pytest.mark.unit
FIXTURE = Path(__file__).parent / "fixtures/micro_game"


def network(points, routes):
    result = SplineNetwork({i: Anchor(i, *p) for i, p in points.items()})
    for index, (a, b, kind, interior) in enumerate(routes):
        refs = (a, *interior, b)
        sid = (index << 8) | kind
        result.strips[sid] = Strip(sid, refs)
        cid = connection_id(a, b, kind)
        result.connections[cid] = Connection(cid, (sid,))
    return result


def locators(states, points):
    tables = {}
    for suffix, hub in enumerate(("city", "farm", "mine", "port", "wood")):
        rows = []
        for state in states.values():
            if state.get(hub):
                x, z = points[int(state["id"]) * 100 + suffix]
                rows.append({"id": state["id"], "position": [x, 0, z]})
        tables[hub] = {"game_object_locator": {"instances": rows}}
    return tables


def chain_case() -> tuple[SplineNetwork, dict, dict, dict, dict, dict, Geography]:
    old = {
        name: {"id": i, "city": f"x{i:06X}", "provinces": [f"x{i:06X}"]}
        for i, name in enumerate(("A", "A2", "B", "B2"), 1)
    }
    final = {
        "A": {**old["A"], "provinces": ["x000001", "x000002"]},
        "B": {**old["B"], "provinces": ["x000003", "x000004"]},
    }
    points = {100: (0, 0), 200: (1, 1), 300: (4, 0), 400: (3, 1)}
    source = network(points, [(100, 200, 0, ()), (200, 400, 0, ()), (400, 300, 1, ())])
    geo = Geography(required={("A", "B"): [{"kind": "land", "pixel": [2, 0]}]})
    return (
        source,
        old,
        final,
        locators(old, points),
        locators(final, points),
        {"A": ["A2"], "B": ["B2"]},
        geo,
    )


def test_binary_roundtrip_preserves_unsorted_records_and_multi_strip_chain():
    source = network({300: (3, 0), 100: (0, 0), INTERMEDIATE: (1, 0)}, [])
    source.strips = {
        257: Strip(257, (INTERMEDIATE, 300)),
        1: Strip(1, (INTERMEDIATE, 100)),
    }
    cid = connection_id(100, 300, 1)
    source.connections[cid] = Connection(cid, (257, 1))
    encoded = source.to_bytes()
    parsed = SplineNetwork.from_bytes(encoded)
    assert parsed.to_bytes() == encoded
    assert list(parsed.anchors) == [300, 100, INTERMEDIATE]
    assert parsed.connection_path(parsed.connections[cid]) == (100, INTERMEDIATE, 300)
    parsed.validate_references()
    assert not encoded.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("cut", [0, 1, 5, 15, 40, 62, -1])
def test_truncated_binary_rejected(cut):
    raw = network({100: (1, 2)}, []).to_bytes()
    with pytest.raises(ValueError):
        SplineNetwork.from_bytes(raw[:cut])


def test_bad_schema_counts_duplicate_ids_and_nonfinite_coordinates():
    raw = bytearray(network({100: (1, 2), 101: (2, 3)}, []).to_bytes())
    bad = raw.copy()
    struct.pack_into("<i", bad, 6, 5)
    with pytest.raises(ValueError, match="version"):
        SplineNetwork.from_bytes(bad)
    bad = raw.copy()
    struct.pack_into("<i", bad, 18, -1)
    with pytest.raises(ValueError, match="counts"):
        SplineNetwork.from_bytes(bad)
    bad = raw.copy()
    struct.pack_into("<I", bad, 84, 100)
    with pytest.raises(ValueError, match="Duplicate"):
        SplineNetwork.from_bytes(bad)
    bad = raw.copy()
    struct.pack_into("<f", bad, 62, math.nan)
    with pytest.raises(ValueError, match="coordinate"):
        SplineNetwork.from_bytes(bad)
    with pytest.raises(ValueError, match="trailing"):
        SplineNetwork.from_bytes(raw + b"\x00\x00")
    bad = raw.copy()
    struct.pack_into("<H", bad, 36, 999)
    with pytest.raises(ValueError, match="schema"):
        SplineNetwork.from_bytes(bad)


def test_packed_ids_and_record_integrity():
    assert anchor_id(100, 1) == NAVAL | 100
    assert anchor_id(0, 0, True) == INTERMEDIATE
    assert endpoints(connection_id(NAVAL | 100, NAVAL | 200, 3)) == (
        NAVAL | 100,
        NAVAL | 200,
        3,
    )
    for args in [(NAVAL, 0), (1, 32), (-1, 0)]:
        with pytest.raises(ValueError):
            anchor_id(*args)
    with pytest.raises(ValueError):
        connection_id(1 << 29, 2, 0)
    source = network({100: (1, 2)}, [])
    source.anchors[100] = Anchor(101, 1, 2)
    with pytest.raises(ValueError, match="anchor ID"):
        source.to_bytes()


def test_chain_reconstruction_demotes_hubs_and_preserves_geometry_without_mutation(
    spline_logs,
):
    args = chain_case()
    before = deepcopy(args)
    result = merge_spline_network(*args)
    result.network.validate_references()
    assert args == before
    key = connection_id(100, 300, 1)
    path = result.network.connection_path(result.network.connections[key])
    assert [
        (result.network.anchors[n].x, result.network.anchors[n].z) for n in path
    ] == [(0, 0), (1, 1), (3, 1), (4, 0)]
    assert all(n & INTERMEDIATE for n in path[1:-1])
    assert 200 not in result.network.anchors and 400 not in result.network.anchors
    assert result.status == "complete"
    assert spline_logs("route")[0]["type_conversion"]
    again = merge_spline_network(*args)
    assert result.data == again.data and result.status == again.status


def test_competing_crossings_select_shorter_route_and_preserve_untouched_type(
    spline_logs,
    caplog,
):
    args: list[Any] = list(chain_case())
    source = args[0]
    source.anchors[INTERMEDIATE] = Anchor(INTERMEDIATE, 2, 20)
    source.strips[513] = Strip(513, (400, INTERMEDIATE, 300))
    source.anchors[201] = Anchor(201, 1, 0)
    source.strips[768] = Strip(768, (200, 201, 300))
    cid = connection_id(200, 300, 0)
    source.connections[cid] = Connection(cid, (768,))
    result = merge_spline_network(*args)
    path = result.network.connection_path(
        result.network.connections[connection_id(100, 300, 1)]
    )
    assert not any(result.network.anchors[n].z == 20 for n in path)
    args[0] = network({100: (0, 0), 300: (4, 0)}, [(100, 300, 0, ())])
    caplog.clear()
    result = merge_spline_network(*args)
    assert connection_id(100, 300, 0) in result.network.connections
    assert spline_logs("route")[0]["action"] == "preserve"


def test_internal_components_mst_split_at_retained_hubs():
    source, old, _, _ol, _, _, _ = chain_case()
    old["A"]["farm"] = old["A2"]["city"]
    # The original farm donor is separate from the removed A2 city.
    source.anchors[101] = Anchor(101, 2, 0)
    source.strips[1025] = Strip(1025, (200, 101))
    c = connection_id(200, 101, 1)
    source.connections[c] = Connection(c, (1025,))
    final = {
        "A": {
            **old["A"],
            "provinces": ["x000001", "x000002", "x000003", "x000004"],
            "mine": "x000003",
        }
    }
    old["B"]["mine"] = "x000003"
    source.anchors[302] = Anchor(302, 4, 1)
    source.strips[1281] = Strip(1281, (300, 302))
    c = connection_id(300, 302, 1)
    source.connections[c] = Connection(c, (1281,))
    points = {i: (p.x, p.z) for i, p in source.anchors.items()}
    final_points = {100: points[100], 101: points[101], 102: points[302]}
    result = merge_spline_network(
        source,
        old,
        final,
        locators(old, points),
        locators(final, final_points),
        {"A": ["A2", "B", "B2"]},
        Geography(),
    )
    assert result.status == "complete"
    assert len(result.network.connections) == 2
    assert all(
        not (n in (100, 101, 102))
        for c in result.network.connections.values()
        for n in result.network.connection_path(c)[1:-1]
    )


def test_missing_and_moved_hubs_export_structurally_valid_drafts(spline_logs):
    args: list[Any] = list(chain_case())
    args[0].anchors.pop(200)
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    } >= {"unconnected_state"}
    assert "missing_state_connection" in {i["kind"] for i in spline_logs("advisory")}
    assert {i["kind"] for i in spline_logs("reconstruction", "advisory")} >= {
        "quarantined_strip",
        "quarantined_connection",
    }
    result.network.validate_references()
    args: list[Any] = list(chain_case())
    args[4]["city"]["game_object_locator"]["instances"][0]["position"] = [50, 0, 50]
    result = merge_spline_network(*args)
    assert result.network.anchors[100].x == 50
    assert "moved_locator" in {
        i["kind"] for i in spline_logs("reconstruction", "advisory")
    }
    assert not result.network.connections


def test_port_inheritance_reconnects_land_and_preserves_sea_routes(spline_logs):
    old = {
        "A": {"id": 1, "city": "x01"},
        "P": {"id": 2, "city": "x02", "port": "x03", "naval_exit_id": 99},
        "SEA": {"id": 99},
        "SEA2": {"id": 98},
    }
    final = {"A": {"id": 1, "city": "x01", "port": "x03", "naval_exit_id": 99}}
    points = {
        100: (1, 1),
        200: (2, 2),
        203: (3, 3),
        NAVAL | 200: (3, 4),
        NAVAL | 9900: (4, 4),
        NAVAL | 9800: (5, 5),
    }
    source = network(
        points,
        [
            (100, 200, 0, ()),
            (200, 203, 0, ()),
            (NAVAL | 200, NAVAL | 9900, 3, ()),
            (NAVAL | 9900, NAVAL | 9800, 2, ()),
        ],
    )
    fp = {100: points[100], 103: points[203]}
    arguments = [
        source,
        old,
        final,
        locators(old, points),
        locators(final, fp),
        {"A": ["P"]},
        Geography(
            size=(6, 6),
            placement_available=True,
            province_samples={(3, 3): 3, (3, 2): 255},
            province_owners={3: "A", 255: "SEA"},
            sea_provinces={255},
            coastal_provinces={3},
        ),
    ]
    result = merge_spline_network(*arguments)
    assert result.status == "complete"
    assert connection_id(100, 103, 1) in result.network.connections
    assert connection_id(NAVAL | 100, NAVAL | 9900, 3) in result.network.connections
    assert connection_id(NAVAL | 9800, NAVAL | 9900, 2) in result.network.connections
    assert result.network.anchors[NAVAL | 100].z == 4
    source.anchors.pop(NAVAL | 200)
    result = merge_spline_network(*arguments)
    assert {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    } >= {
        "missing_harbor_geometry",
        "missing_harbor_connection",
    }
    result.network.validate_references()
    final["A"]["naval_exit_id"] = 98
    result = merge_spline_network(*arguments)
    assert result.status == "draft"


@pytest.mark.parametrize("problem", ["duplicate", "shape", "nan"])
def test_invalid_locators_rejected(problem):
    rows = [{"id": 1, "position": [1, 0, 2]}]
    if problem == "duplicate":
        rows *= 2
    elif problem == "shape":
        rows[0]["position"] = [1]
    else:
        rows[0]["position"][0] = float("nan")
    with pytest.raises(ValueError):
        locator_positions({"city": {"game_object_locator": {"instances": rows}}})


def geography_files(tmp_path, pixels, size, extra="", wrap="no", csv=""):
    tmp_path.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size)
    image.putdata([(0, 0, c) for c in pixels])
    image.save(tmp_path / "provinces.png")
    (tmp_path / "default.map").write_text(
        f"wrap_x = {wrap}\nsea_starts = {{ x0000FF }}\n{extra}"
    )
    (tmp_path / "adjacencies.csv").write_text("From;To;Type;Through;Comment\n" + csv)
    return (
        tmp_path / "provinces.png",
        tmp_path / "default.map",
        tmp_path / "adjacencies.csv",
    )


def test_geography_contact_wrap_water_blockers_straits_and_cache(tmp_path, monkeypatch):
    states = {
        "A": {"id": 1, "city": "x01", "provinces": ["x01"]},
        "B": {"id": 2, "city": "x02", "provinces": ["x02"]},
        "C": {
            "id": 3,
            "city": "x03",
            "provinces": ["x03"],
            "impassable": ["x03", "x999999"],
        },
    }
    files = geography_files(
        tmp_path,
        [1, 255, 2, 3],
        (2, 2),
        csv="x01;x02;sea;-1;strait\nx02;x03;impassable;-1;blocked\n",
    )
    cache = tmp_path / "cache"
    result = build_geography(*files, states, cache)
    assert ("A", "B") not in result.required
    assert result.straits[("A", "B")][0]["kind"] == "strait"
    assert result.adjacent("A", "B") is True
    assert result.blocked and result.issues[0]["kind"] == "out_of_state_impassable"
    from vic3_state_merger.splines import geography

    monkeypatch.setattr(
        geography,
        "_scan_boundaries",
        lambda *_: pytest.fail("cached raster was rescanned"),
    )
    assert build_geography(*files, states, cache).required == result.required
    monkeypatch.undo()
    files = geography_files(tmp_path, [1, 255, 2], (3, 1), wrap="no")
    assert not build_geography(*files, states, cache).required
    files = geography_files(tmp_path, [1, 255, 2], (3, 1), wrap="yes")
    assert ("A", "B") in build_geography(*files, states, cache).required
    assert len(list(cache.glob("*.json"))) == 3
    files = geography_files(tmp_path, [1, 255, 255, 2], (2, 2))
    assert not build_geography(*files, states, cache).required
    files = geography_files(
        tmp_path, [1, 255, 2], (3, 1), csv="x01;x02;sea;-1;strait\n"
    )
    assert (
        build_geography(*files, states, cache).straits[("A", "B")][0]["kind"]
        == "strait"
    )
    states["B"]["provinces"].append("x01")
    with pytest.raises(ValueError, match="multiple"):
        build_geography(*files, states, cache)
    assert color_code("garbage") is None and color_code("xGG") is None


@pytest.mark.integration
def test_spline_only_binary_output_logs_and_source_immutability(tmp_path):
    out, cache = tmp_path / "mod", tmp_path / "data"
    keep = out / "gfx/map/spline_network/style.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("keep")
    original = {p: p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()}
    merger = StateMerger(FIXTURE, out, {"STATE_ALPHA": ["STATE_BETA"]}, cache)
    merger.run(["spline_network"])
    assert merger.spline_result is not None
    assert merger.spline_result.status == "complete"
    assert not hasattr(merger.spline_result, "report")
    assert not hasattr(merger.spline_result, "report_path")
    assert not hasattr(merger, "spline_report_path")
    assert (
        not (out / "map_data").exists()
        and not (out / "gfx/map/map_object_data").exists()
    )
    assert keep.read_text() == "keep"
    raw = (out / NETWORK_PATH).read_bytes()
    SplineNetwork.from_bytes(raw).validate_references()
    assert not (cache / "spline-report.json").exists()
    merger.run(["spline_network"])
    assert (out / NETWORK_PATH).read_bytes() == raw
    assert not (cache / "spline-report.json").exists()
    assert all(p.read_bytes() == content for p, content in original.items())
    merger.run(["map_objects"])
    assert merger.spline_result is None and (out / NETWORK_PATH).read_bytes() == raw


@pytest.mark.integration
def test_errors_do_not_replace_network_and_merged_sources_are_rejected(tmp_path):
    game, out = tmp_path / "game", tmp_path / "out"
    shutil.copytree(FIXTURE, game)
    dest = out / NETWORK_PATH
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"keep")
    (game / NETWORK_PATH).write_bytes(b"broken")
    with pytest.raises(ValueError):
        StateMerger(game, out, {"STATE_ALPHA": ["STATE_BETA"]}, tmp_path / "data").run(
            ["spline_network"]
        )
    assert dest.read_bytes() == b"keep"
    shutil.copyfile(FIXTURE / NETWORK_PATH, game / NETWORK_PATH)
    p = game / "map_data/state_regions/state_merging.txt"
    p.write_text("STATE_ALPHA = { id = 1 }")
    with pytest.raises(ValueError, match="already-merged"):
        StateMerger(
            FIXTURE,
            out,
            {"STATE_ALPHA": ["STATE_BETA"]},
            tmp_path / "data",
            sources={"spline_network": [game]},
        ).run(["spline_network"])
    assert dest.read_bytes() == b"keep"
    with pytest.raises(ValueError, match="outside"):
        StateMerger(FIXTURE, out, {}, out / "data").run(["spline_network"])
    assert "spline_network" in SourceResolver(FIXTURE).roots


def test_cli_draft_exit_and_gui_status(tmp_path, monkeypatch, application_logging):
    result = merge_spline_network(*chain_case())
    result.status = "draft"
    log_path = tmp_path / "merge.log"
    monkeypatch.setattr(cli, "run_merge", lambda **_: result)
    import sys

    monkeypatch.setattr(sys, "argv", ["state-merger", "plan.json", "/game", "/mod"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    status, message = gui._completion_status(result, log_path)
    assert message is not None
    assert status == "Draft exported" and str(log_path) in message
    assert gui._completion_status(None) == ("Completed", None)
    _, message = gui._completion_status(result)
    assert message is not None and "Enable file logging and rerun" in message
    assert (
        not cli.get_parser().parse_args(["p", "g", "m", "--no-splines"]).spline_network
    )


@pytest.mark.live
def test_installed_spline_codec_roundtrip():
    import os

    root = os.environ.get("VIC3_GAME_ROOT")
    if not root:
        pytest.skip("VIC3_GAME_ROOT is not set")
    raw = (Path(root) / NETWORK_PATH).read_bytes()
    parsed = SplineNetwork.from_bytes(raw)
    assert parsed.to_bytes() == raw
    parsed.validate_references()


def test_engine_trailing_decimal_tokens_and_unplaced_locators(spline_logs):
    import pyradox

    from vic3_state_merger.map_object_data import MapObjectData

    text = "game_object_locator = { instances = { { id = 1 position = { 1. 0. 2. } rotation = { -0. 1. 0. 0. } scale = { 1. 1. 1. } } } }"
    parsed = pyradox.parse(text)
    assert isinstance(parsed, pyradox.Tree)
    table = MapObjectData(parsed)
    assert table.instances_list[0]["position"] == [1, 0, 2]
    assert table.instances_list[0]["rotation"] == [0, 1, 0, 0]
    assert table.instances_list[0]["scale"] == [1, 1, 1]
    assert locator_positions({"city": parsed})["city"][1] == (1, 2)
    args: list[Any] = list(chain_case())
    args[4]["city"]["game_object_locator"]["instances"][0]["position"] = [-1, 0, -1]
    result = merge_spline_network(*args)
    assert result.status == "complete"
    assert result.network.anchors[100] == args[0].anchors[100]
    assert "unplaced_final_locator" in {
        i["kind"] for i in spline_logs("reconstruction", "advisory")
    }


@pytest.mark.integration
def test_review_export_uses_final_mod_and_leaves_it_untouched(tmp_path):
    from vic3_state_merger.splines import export_spline_review

    final, review, data = tmp_path / "final", tmp_path / "review", tmp_path / "data"
    plan = {"STATE_ALPHA": ["STATE_BETA"]}
    StateMerger(FIXTURE, final, plan).run(["map_data", "map_objects"])
    before = {
        p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()
    }
    result = export_spline_review(FIXTURE, final, plan, review, data)
    assert result.status == "complete"
    assert list(review.rglob("*.splnet")) == [review / NETWORK_PATH]
    assert {
        p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()
    } == before
    assert result.data == (review / NETWORK_PATH).read_bytes()
    assert not (data / "spline-report.json").exists()
    second = export_spline_review(FIXTURE, final, plan, review, data)
    assert second.data == result.data and second.status == result.status
    with pytest.raises(ValueError, match="overlap"):
        export_spline_review(FIXTURE, final, plan, final / "review", data)
    with pytest.raises(ValueError, match="absorbed"):
        export_spline_review(FIXTURE, FIXTURE, plan, review, data)


@pytest.mark.integration
def test_cli_no_splines_does_not_change_compensation_defaults(tmp_path):
    result = cli.run_merge(
        str(FIXTURE / "merge_states.json"),
        str(tmp_path / "mod"),
        str(FIXTURE),
        str(tmp_path / "data"),
        4,
        False,
        spline_network=False,
    )
    assert result is None
    assert not (tmp_path / "mod" / NETWORK_PATH).exists()
    assert (tmp_path / "mod/common/state_traits/state_merging.txt").exists()


def test_merge_plan_collision_and_missing_final_locator_are_explicit(spline_logs):
    args: list[Any] = list(chain_case())
    args[5] = {"A": ["A2"], "B": ["A2"]}
    with pytest.raises(ValueError, match="unique"):
        merge_spline_network(*args)
    args: list[Any] = list(chain_case())
    args[4]["city"]["game_object_locator"]["instances"] = []
    result = merge_spline_network(*args)
    assert result.status == "draft"
    assert "missing_final_locator" in {
        i["kind"] for i in spline_logs("reconstruction", "advisory")
    }
    assert "locator_validation_unavailable" in {
        i["kind"] for i in spline_logs("game_rule", "implementation", "unverified")
    }
    assert all(
        i["category"] == "unverified"
        for i in spline_logs("game_rule", "implementation", "unverified")
    )
    result.network.validate_references()


@pytest.mark.integration
@pytest.mark.parametrize("review", [False, True])
@pytest.mark.parametrize("changed_input", ["network", "geography", "states", "locator"])
def test_source_changes_abort_before_output_replacement(
    tmp_path, monkeypatch, review, changed_input
):
    import vic3_state_merger.state_merger as orchestration
    from vic3_state_merger.splines import pipeline

    game, final, output = tmp_path / "game", tmp_path / "final", tmp_path / "output"
    shutil.copytree(FIXTURE, game)
    plan = {"STATE_ALPHA": ["STATE_BETA"]}
    StateMerger(game, final, plan, tmp_path / "final-data").run(
        ["map_data", "map_objects"]
    )
    destination = output / NETWORK_PATH
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"previous network")
    # The review adapter must verify the exact final-mod states and locators too.
    root = final if review and changed_input in ("states", "locator") else game
    relative = {
        "network": NETWORK_PATH,
        "geography": "map_data/adjacencies.csv",
        "states": "map_data/state_regions/state_merging.txt"
        if review
        else "map_data/state_regions/01_regions.txt",
        "locator": "gfx/map/map_object_data/generated_map_object_locators_city.txt",
    }[changed_input]
    prepare = pipeline.prepare_spline_merge

    def change_after_preparation(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        path = root / relative
        path.write_bytes(path.read_bytes() + b"\nchanged")
        return prepared

    adapter = pipeline if review else orchestration
    monkeypatch.setattr(adapter, "prepare_spline_merge", change_after_preparation)
    with pytest.raises(ValueError, match="Spline input changed during reconstruction"):
        if review:
            pipeline.export_spline_review(game, final, plan, output, tmp_path / "data")
        else:
            StateMerger(game, output, plan, tmp_path / "data").run(["spline_network"])
    assert destination.read_bytes() == b"previous network"
    assert not (tmp_path / "data/spline-report.json").exists()
