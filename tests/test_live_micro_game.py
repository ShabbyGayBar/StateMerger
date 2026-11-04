# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Optional installed-game smoke test; never writes to the game directory."""

import json
import os
from pathlib import Path

import pytest

from vic3_state_merger.cli import run_merge
from vic3_state_merger.state_merger import StateMerger


@pytest.mark.live
def test_installed_game_smoke(tmp_path):
    game_root = os.environ.get("VIC3_GAME_ROOT")
    if not game_root:
        pytest.skip("VIC3_GAME_ROOT is not set")
    assert game_root is not None
    plan = tmp_path / "live-plan.json"
    plan.write_text(
        json.dumps({"STATE_MASSACHUSETTS": ["STATE_MAINE", "STATE_VERMONT"]}),
        encoding="utf-8",
    )
    output = tmp_path / "mod"
    run_merge(str(plan), str(output), game_root, str(tmp_path / "cache"), 4, False)
    assert (output / "map_data/state_regions/state_merging.txt").exists()
    assert (
        (output / "common/history/states/00_states.txt")
        .read_bytes()
        .startswith(b"\xef\xbb\xbf")
    )


@pytest.mark.live
def test_installed_french_dlc_city_type_adaptations(tmp_path):
    game_root = os.environ.get("VIC3_GAME_ROOT")
    if not game_root:
        pytest.skip("VIC3_GAME_ROOT is not set")
    game = Path(game_root)
    relative = Path("gfx/map/city_data/city_types")
    pack = game / "dlc/dlc004_voice_of_the_people"
    names = [f"french_{hub}.txt" for hub in ("city", "farm", "mine", "port", "wood")]
    if not all((pack / relative / name).is_file() for name in names):
        pytest.skip("Voice of the People French city-type scripts are not installed")
    output = tmp_path / "mod"
    StateMerger(
        game,
        output,
        {"STATE_FLANDERS": ["STATE_WALLONIA"], "STATE_PROVENCE": ["STATE_SAVOY"]},
    ).run(["misc"])
    for name in names:
        original = (pack / relative / name).read_text(encoding="utf-8-sig")
        raw = (output / relative / name).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        assert text == original.replace("STATE_WALLONIA", "STATE_FLANDERS").replace(
            "STATE_SAVOY", "STATE_PROVENCE"
        )
        assert "s:STATE_WALLONIA" not in text and "s:STATE_SAVOY" not in text
        assert "s:STATE_FLANDERS" in text and "s:STATE_PROVENCE" in text
        assert "has_dlc_feature = voice_of_the_people_content" in text
    assert not (output / "dlc").exists()
