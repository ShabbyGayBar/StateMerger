# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""File selection and execution-option validation without writing mod output."""

from pathlib import Path

import pytest

from vic3_state_merger.cli import _execution_options, get_parser
from vic3_state_merger.sources import SourceResolver, validate_names

pytestmark = pytest.mark.unit


def test_file_overlays_empty_winners_and_sorted_order(tmp_path):
    vanilla, low, high = [tmp_path / name for name in ("vanilla", "low", "high")]
    for root in (vanilla, low, high):
        root.mkdir()
    (vanilla / "z.txt").write_text("z")
    (vanilla / "a.txt").write_text("vanilla")
    (vanilla / "ignore.yml").write_text("ignored")
    (vanilla / "folder.txt").mkdir()
    (low / "a.txt").write_text("low")
    (high / "a.txt").write_text("")
    (high / "b.txt").write_text("high")
    resolver = SourceResolver(vanilla, {"map_data": [vanilla, low, high]})
    files = resolver.files("map_data", "")
    assert list(files) == ["a.txt", "b.txt", "z.txt"]
    assert files["a.txt"] == high / "a.txt"
    assert files["a.txt"].read_text() == ""
    assert resolver.roots["state"] == (vanilla,)
    assert list(resolver.files("map_data", "", by_layer=True)) == [
        "z.txt",
        "a.txt",
        "b.txt",
    ]
    assert resolver.files("map_data", "missing") == {}


def test_dlc_discovery_order_overrides_and_opt_out(tmp_path):
    root = tmp_path / "game"
    relative = "gfx/map/city_data/city_types"

    def write(prefix, name, text):
        path = root / prefix / relative / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    base = write("", "shared.txt", "base")
    # Create in reverse order so filesystem iteration cannot define precedence.
    winner = write("dlc/z_pack", "shared.txt", "last pack")
    write("dlc/a_pack", "shared.txt", "first pack")
    only_dlc = write("dlc/a_pack", "a.txt", "DLC only")
    empty = write("dlc/z_pack", "empty.txt", "")
    write("", "empty.txt", "base")
    write("dlc/a_pack", "ignored.yml", "ignored")
    write("dlc/a_pack", "nested/ignored.txt", "ignored")
    write("dlc/a_pack/dlc/nested_pack", "ignored.txt", "ignored")
    (root / "dlc/not_a_pack.txt").write_text("ignored")
    (root / "dlc/z_pack" / relative / "directory.txt").mkdir()
    resolver = SourceResolver(root)
    assert resolver.files("misc", relative) == {
        "a.txt": only_dlc,
        "empty.txt": empty,
        "shared.txt": winner,
    }
    assert list(resolver.files("misc", relative)) == [
        "a.txt",
        "empty.txt",
        "shared.txt",
    ]
    assert resolver.files("misc", relative, include_dlc=False) == {
        "empty.txt": root / relative / "empty.txt",
        "shared.txt": base,
    }
    assert resolver.files("misc", "missing") == {}


def test_later_source_root_overrides_earlier_dlc_including_empty_files(tmp_path):
    game, mod = tmp_path / "game", tmp_path / "mod"
    relative = "events"
    for root in (game, mod):
        (root / relative).mkdir(parents=True)
        (root / "dlc/z_pack" / relative).mkdir(parents=True)
    early = game / "dlc/z_pack" / relative
    (early / "a.txt").write_text("earlier DLC")
    (early / "z.txt").write_text("earlier DLC")
    (early / "shared.txt").write_text("earlier DLC")
    (mod / relative / "shared.txt").write_text("")
    (mod / relative / "b.txt").write_text("later root")
    (mod / "dlc/z_pack" / relative / "b.txt").write_text("later DLC")
    resolver = SourceResolver(game, {"misc": [game, mod]})
    files = resolver.files("misc", relative)
    assert files["shared.txt"] == mod / relative / "shared.txt"
    assert files["shared.txt"].read_text() == ""
    assert files["b.txt"].read_text() == "later DLC"
    assert files["z.txt"] == early / "z.txt"
    assert list(files) == ["a.txt", "b.txt", "shared.txt", "z.txt"]
    assert list(resolver.files("misc", relative, by_layer=True)) == [
        "a.txt",
        "z.txt",
        "b.txt",
        "shared.txt",
    ]


@pytest.mark.parametrize(
    "sources",
    [
        [],
        {"unknown": ["game"]},
        {"map_data": []},
        {"map_data": [""]},
        {"map_data": [5]},
    ],
)
def test_invalid_source_configuration(sources):
    with pytest.raises((ValueError, TypeError)):
        SourceResolver("game", sources)


@pytest.mark.parametrize("stack", ["game", Path("game"), {"game"}])
def test_sources_require_ordered_lists(stack):
    with pytest.raises(TypeError, match="ordered root list"):
        SourceResolver("game", {"map_data": stack})


@pytest.mark.parametrize("names", ["misc", ["misc", "misc"], ["bad"], [42]])
def test_stage_names_are_validated(names):
    with pytest.raises((ValueError, TypeError)):
        validate_names(names, ("misc",), "stages")


def test_source_root_validation_and_overlap(tmp_path):
    resolver = SourceResolver(tmp_path, {"map_data": [tmp_path / "missing"]})
    with pytest.raises(ValueError, match="map_data.*searched roots"):
        resolver.validate(["map_data"])
    for destination in (tmp_path, tmp_path.parent, tmp_path / "child"):
        with pytest.raises(ValueError, match="overlaps input root"):
            resolver.check_destination(destination, ["state"])
    resolver.check_destination(tmp_path.parent / "other", ["state"])


@pytest.mark.parametrize("option", ["--stages", "--assets"])
def test_cli_comma_lists_reject_empty_names(option):
    with pytest.raises(SystemExit):
        get_parser().parse_args(["plan", "game", "out", option, "map_data,"])


@pytest.mark.parametrize("value", ["map_data", "bad=root", "map_data="])
def test_cli_invalid_source_syntax(value):
    with pytest.raises(SystemExit):
        get_parser().parse_args(["plan", "game", "out", "--source", value])


@pytest.mark.parametrize(
    "config",
    [
        "[]",
        '{"unknown": 1}',
        '{"sources": null}',
        '{"sources": {"misc": "root"}}',
        '{"stages": "misc"}',
        '{"assets": null}',
        '{"integration_traits": 1}',
    ],
)
def test_invalid_config_schema(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(config)
    with pytest.raises((ValueError, TypeError)):
        _execution_options(path, None, None, None, None)
