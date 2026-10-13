# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copied to a temporary directory and executed by the wheel's isolated Python."""

import codecs
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pyradox

import vic3_state_merger


def main():
    cli, expected, venv = sys.argv[1:]
    package = Path(vic3_state_merger.__file__).resolve()
    assert package.is_relative_to(Path(venv).resolve()), package
    assert version("vic3-state-merger") == vic3_state_merger.__version__ == expected

    def run(*args):
        return subprocess.run(
            [cli, *args], check=True, capture_output=True, text=True, timeout=60
        ).stdout

    assert "merge_file" in run("--help")
    assert run("--version").strip() == f"state-merger {expected}"
    legal = run("--license")
    assert "GPL-3.0-or-later" in legal and "LicenseRef-Paradox-UGC" in legal
    work = Path.cwd()
    fixture, output = work / "micro_game", work / "mod"
    run(
        str(fixture / "merge_states.json"),
        str(fixture),
        str(output),
        "--data-dir",
        str(work / "cache"),
    )
    checks = {
        "map_data/state_regions/state_merging.txt": (
            "STATE_ALPHA",
            "arable_land = 8",
            "xA1",
            "xB2",
        ),
        "common/history/states/00_states.txt": ("s:STATE_ALPHA", "c:CLAIM_B"),
        "common/history/buildings/state_merging.txt": (
            "building_coal_mine",
            "levels = 5",
        ),
        "common/history/pops/state_merging.txt": ("size = 150",),
        "common/history/trade/00_historical_trade.txt": (
            "add_exports = 6",
            "add_imports = 8",
        ),
    }
    for relative, tokens in checks.items():
        path = output / relative
        raw = path.read_bytes()
        assert raw.startswith(codecs.BOM_UTF8), relative
        text = raw.decode("utf-8-sig")
        assert "STATE_BETA" not in text, relative
        assert all(token in text for token in tokens), relative
        assert (
            pyradox.parse_file(str(path), game="HoI4", path_relative_to_game=False)
            is not None
        )
    for relative in (
        "common/state_traits/state_merging.txt",
        "common/flag_definitions/state_merging_flag_definition_usa.txt",
        "common/script_values/state_merging_usa_state_counter.txt",
        "localization/english/hub_names_states_merging_l_english.yml",
    ):
        assert (output / relative).read_bytes().startswith(codecs.BOM_UTF8), relative
    protected = (output / "common/decisions/state_merging.txt").read_text(
        encoding="utf-8-sig"
    )
    assert "STATE_BETA_ANJOU" in protected
    print(
        f"Installed wheel {expected}: CLI, merge semantics, bundled overrides, and BOM checks passed"
    )


if __name__ == "__main__":
    main()
