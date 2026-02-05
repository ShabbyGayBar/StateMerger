import argparse
import json
import os
from typing import Optional

from vic3_state_merger import __version__
from vic3_state_merger.state_merger import StateMerger


DEFAULT_WINDOWS_GAME_ROOT = (
    "C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game/"
)
DEFAULT_LINUX_GAME_ROOT = os.path.expandvars(
    "$HOME/.local/share/Steam/steamapps/common/Victoria 3/game/"
)


def _ensure_trailing_sep(path: str) -> str:
    if not path:
        return path
    if path.endswith("/") or path.endswith("\\"):
        return path
    return path + "/"


def _default_game_root() -> str:
    if os.path.exists(DEFAULT_WINDOWS_GAME_ROOT):
        return DEFAULT_WINDOWS_GAME_ROOT
    if os.path.exists(DEFAULT_LINUX_GAME_ROOT):
        return DEFAULT_LINUX_GAME_ROOT
    return DEFAULT_WINDOWS_GAME_ROOT


def _default_data_dir(mod_dir: str) -> str:
    mod_dir = os.path.abspath(mod_dir)
    parent = os.path.dirname(mod_dir.rstrip("/\\"))
    candidate = os.path.join(parent, "data")
    if os.path.isdir(candidate):
        return candidate
    return os.path.join(os.getcwd(), "data")


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="state-merger",
        description="Merge Victoria 3 states based on a merge plan JSON file.",
    )
    parser.add_argument(
        "merge_file",
        help="Path to merge_states.json (merge plan).",
    )
    parser.add_argument(
        "mod_dir",
        help="Target mod output folder.",
    )
    parser.add_argument(
        "--game-root",
        dest="game_root",
        default=_default_game_root(),
        help="Victoria 3 game root directory.",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Cache/data directory (defaults to sibling of mod_dir).",
    )
    parser.add_argument(
        "--small-state-limit",
        type=int,
        default=4,
        help="Limit for small states when merging.",
    )
    parser.add_argument(
        "--ignore-small-states",
        dest="ignore_small_states",
        action="store_true",
        help="Ignore small states when merging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def print_help(parser: Optional[argparse.ArgumentParser] = None) -> None:
    if parser is None:
        parser = get_parser()
    parser.print_help()


def print_version() -> None:
    print(f"state-merger {__version__}")


def run_merge(
    merge_file: str,
    mod_dir: str,
    game_root: str,
    data_dir: Optional[str],
    small_state_limit: int,
    ignore_small_states: bool,
) -> None:
    with open(merge_file, "r", encoding="utf-8") as file:
        merge_dict = json.load(file)

    resolved_data_dir = data_dir or _default_data_dir(mod_dir)

    state_merger = StateMerger(
        _ensure_trailing_sep(game_root),
        _ensure_trailing_sep(mod_dir),
        merge_dict,
        _ensure_trailing_sep(resolved_data_dir),
    )
    state_merger.merge_state_data(ignoreSmallStates=ignore_small_states, smallStateLimit=small_state_limit)
    state_merger.merge_misc_data()
    state_merger.merge_loc_data()


def main() -> None:
    parser = get_parser()
    args = parser.parse_args()
    run_merge(
        merge_file=args.merge_file,
        mod_dir=args.mod_dir,
        game_root=args.game_root,
        data_dir=args.data_dir,
        small_state_limit=args.small_state_limit,
        ignore_small_states=args.ignore_small_states,
    )