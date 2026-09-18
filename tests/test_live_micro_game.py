"""Optional installed-game smoke test; never writes to the game directory."""

import json
import os

import pytest

from vic3_state_merger.cli import run_merge


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
