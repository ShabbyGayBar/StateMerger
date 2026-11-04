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
