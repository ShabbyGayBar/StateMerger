import argparse
import json
from typing import Optional

from vic3_state_merger import __version__
from vic3_state_merger.state_merger import StateMerger


def _ensure_trailing_sep(path: str) -> str:
    if not path:
        return path
    if path.endswith("/") or path.endswith("\\"):
        return path
    return path + "/"

def _default_data_dir(mod_dir: str) -> str:
    import os

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
        "game_root",
        help="Victoria 3 game root directory.",
    )
    parser.add_argument(
        "mod_dir",
        help="Target mod output folder.",
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


_HUB_TYPES = {"city", "port", "farm", "mine", "wood"}


def load_merge_config(path: str) -> tuple[dict, dict]:
    """Load a merge configuration file and return ``(merge_dict, hub_overrides)``.

    The file must be a JSON file whose keys are state IDs. Each value may be:

    * A **list** of state IDs to merge into the key state (original format,
      fully backward-compatible)::

        {
            "STATE_A": ["STATE_B", "STATE_C"]
        }

    * A **dict** with a ``"merge"`` key (list of states to merge) and optional
      hub-type keys (``"city"``, ``"port"``, ``"farm"``, ``"mine"``, ``"wood"``)
      whose values are the state ID whose original hub province should be used for
      the merged state::

        {
            "STATE_A": {
                "merge": ["STATE_B", "STATE_C"],
                "city": "STATE_B",
                "port": "STATE_C"
            }
        }

    Hub types not listed use the default merge behavior (diner's hub is kept
    unless it is empty, in which case the food state's hub is used).

    Returns:
        merge_dict:    {diner: [food_list]}
        hub_overrides: {diner: {hub_type: source_state}}
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    merge_dict: dict = {}
    hub_overrides: dict = {}

    for state, value in raw.items():
        if isinstance(value, list):
            merge_dict[state] = value
        elif isinstance(value, dict):
            merge_dict[state] = value.get("merge", [])
            overrides = {k: v for k, v in value.items() if k in _HUB_TYPES}
            if overrides:
                hub_overrides[state] = overrides
        else:
            raise ValueError(
                f"Invalid merge config value for state '{state}': expected list or dict, got {type(value).__name__}"
            )

    return merge_dict, hub_overrides


def run_merge(
    merge_file: str,
    mod_dir: str,
    game_root: str,
    data_dir: Optional[str],
    small_state_limit: int,
    ignore_small_states: bool,
) -> None:
    merge_dict, hub_overrides = load_merge_config(merge_file)

    resolved_data_dir = data_dir or _default_data_dir(mod_dir)

    state_merger = StateMerger(
        _ensure_trailing_sep(game_root),
        _ensure_trailing_sep(mod_dir),
        merge_dict,
        _ensure_trailing_sep(resolved_data_dir),
        hub_overrides=hub_overrides,
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