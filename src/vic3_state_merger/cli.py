# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import json
import logging
from pathlib import Path

from vic3_state_merger import __version__
from vic3_state_merger.legal import LICENSE_NOTICE
from vic3_state_merger.logging_config import configure_logging
from vic3_state_merger.sources import ASSETS, STAGES, SourceResolver, validate_names
from vic3_state_merger.state_merger import StateMerger

logger = logging.getLogger(__name__)


def _ensure_trailing_sep(path: str) -> str:
    if not path:
        return path
    if path.endswith(("/", "\\")):
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
        "--stages",
        type=_comma_names,
        help=f"Comma-separated stages (default: all): {', '.join(STAGES)}.",
    )
    parser.add_argument(
        "--source",
        action="append",
        type=_source_pair,
        help="STAGE=ROOT; repeat per stage in increasing priority order. Replaces its configured stack.",
    )
    parser.add_argument("--config", help="Separate merge execution JSON configuration.")
    parser.add_argument(
        "--integration-traits",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Inject integration compensation and write its bundled definitions.",
    )
    parser.add_argument(
        "--assets",
        type=_comma_names,
        help=f"Comma-separated bundled assets or 'none': {', '.join(ASSETS)}.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--license",
        action="version",
        version=LICENSE_NOTICE,
        help="Show license, warranty, and third-party notice information.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="Diagnostic verbosity for stderr and the optional log file (default: INFO).",
    )
    parser.add_argument(
        "--log-file", help="Also save diagnostics to a rotating UTF-8 log file."
    )
    return parser


def print_help(parser: argparse.ArgumentParser | None = None) -> None:
    if parser is None:
        parser = get_parser()
    parser.print_help()


def print_version() -> None:
    print(f"state-merger {__version__}")


def _comma_names(value: str) -> list[str]:
    if value == "none":
        return []
    names = [name.strip() for name in value.split(",")]
    if not all(names):
        raise argparse.ArgumentTypeError("Expected comma-separated nonempty names")
    return names


def _source_pair(value: str) -> tuple[str, str]:
    stage, separator, root = value.partition("=")
    if not separator or stage not in STAGES or not root:
        raise argparse.ArgumentTypeError(
            "Expected STAGE=ROOT with a known stage and nonempty root"
        )
    return stage, root


def _execution_options(config, stages, sources, integration_traits, assets):
    """Resolve config-relative roots, then replace fields explicitly set by CLI/API."""
    options = {}
    if config is not None:
        path = Path(config).resolve()
        with path.open(encoding="utf-8-sig") as handle:
            options = json.load(handle)
        allowed = {"stages", "sources", "integration_traits", "assets"}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError(
                f"Configuration must be an object with only: {sorted(allowed)}"
            )
        if "sources" in options:
            # Reuse library validation before resolving paths; strings must not
            # accidentally become character-by-character source stacks.
            if not isinstance(options["sources"], dict):
                raise ValueError("Configuration sources must be an object")
            SourceResolver(path.parent, options["sources"])
            options["sources"] = {
                stage: [str((path.parent / root).resolve()) for root in roots]
                for stage, roots in options["sources"].items()
            }
        for field in ("stages", "assets"):
            if field in options and not isinstance(options[field], list):
                raise ValueError(f"Configuration {field} must be an array")
        if "integration_traits" in options and not isinstance(
            options["integration_traits"], bool
        ):
            raise ValueError("Configuration integration_traits must be a boolean")
    if sources is not None:
        SourceResolver(Path.cwd(), sources)
        options["sources"] = {**options.get("sources", {}), **sources}
    if stages is not None:
        options["stages"] = stages
    if integration_traits is not None:
        options["integration_traits"] = integration_traits
    if assets is not None:
        options["assets"] = assets
    for field, choices in (("stages", STAGES), ("assets", ASSETS)):
        if field in options:
            options[field] = validate_names(options[field], choices, field)
    return options


def run_merge(
    merge_file: str,
    mod_dir: str,
    game_root: str,
    data_dir: str | None,
    small_state_limit: int,
    ignore_small_states: bool,
    *,
    stages=None,
    sources=None,
    integration_traits: bool | None = None,
    assets=None,
    config: str | None = None,
) -> None:
    with open(merge_file, "r", encoding="utf-8") as file:
        merge_dict = json.load(file)

    resolved_data_dir = data_dir or _default_data_dir(mod_dir)

    configured = any(
        value is not None
        for value in (stages, sources, integration_traits, assets, config)
    )
    options = _execution_options(config, stages, sources, integration_traits, assets)

    state_merger = StateMerger(
        _ensure_trailing_sep(game_root),
        _ensure_trailing_sep(mod_dir),
        merge_dict,
        _ensure_trailing_sep(resolved_data_dir),
        sources=options.get("sources"),
    )
    state_merger.run(
        stages=options.get("stages", STAGES),
        integration_traits=options.get("integration_traits", not configured),
        assets=options.get("assets", () if configured else ASSETS),
        ignore_small_states=ignore_small_states,
        small_state_limit=small_state_limit,
    )
    logger.info("Merge completed: %s", mod_dir)


def main() -> None:
    parser = get_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    try:
        if args.log_file:
            configure_logging(args.log_level, log_file=args.log_file)
        sources = None
        if args.source is not None:
            sources = {}
            for stage, root in args.source:
                sources.setdefault(stage, []).append(root)
        run_merge(
            merge_file=args.merge_file,
            mod_dir=args.mod_dir,
            game_root=args.game_root,
            data_dir=args.data_dir,
            small_state_limit=args.small_state_limit,
            ignore_small_states=args.ignore_small_states,
            stages=args.stages,
            sources=sources,
            integration_traits=args.integration_traits,
            assets=args.assets,
            config=args.config,
        )
    except Exception:
        logger.critical("Merge or logging setup failed", exc_info=True)
        raise SystemExit(1) from None
