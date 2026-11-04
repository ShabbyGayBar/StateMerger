# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core orchestration module for Victoria 3 state merging.

This module contains the :class:`StateMerger` class which drives the full
merge pipeline, as well as a collection of helper utilities for parsing
Paradox ``.txt`` files, performing keyword replacement on arbitrary game
data, and writing output in the correct encoding (UTF-8 BOM).

Merge pipeline overview
-----------------------
1. **State data** – map regions, buildings, pops, states, and trade routes
   are parsed, merged according to the user-supplied *merge dict*, and
   written to the mod output directory.
2. **Map-object data** – city / farm / mine / port / wood locator instances
   are retargeted so merged states retain a valid map pin.
3. **Misc data** – keyword replacement (or removal) is applied across a
   broad set of game directories (AI strategies, decisions, events, …) so
   that references to consumed states are updated to the survivor.
4. **Localization** – hub-name YML files are patched so merged states keep
   readable names on the map.
5. **Bundled assets** – static override files (state traits, USA flag
   definitions, USA state counter) are copied into the mod directory.

The module also provides :func:`_parse_merge` and
:func:`_clean_v3_yml_numbered_keys` which are used by the data-layer
modules as well.
"""

import json
import logging
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import pyradox
import yaml

import vic3_state_merger.assets.flag_definitions_usa
import vic3_state_merger.assets.state_traits
import vic3_state_merger.assets.usa_state_counter
from vic3_state_merger.buildings import Buildings
from vic3_state_merger.map_object_data import MapObjectData
from vic3_state_merger.pops import Pops
from vic3_state_merger.sources import ASSETS, STAGES, SourceResolver, validate_names
from vic3_state_merger.state_regions import StateRegion
from vic3_state_merger.states import States
from vic3_state_merger.trade import Trade

logger = logging.getLogger(__name__)

# Mapping of logical category names to relative paths under the game root.
# Each key corresponds to one of the five core data categories parsed and
# merged by :class:`StateMerger`.
STATE_FILE_DIR = {
    "map_data": r"map_data/state_regions",
    "state": r"common/history/states",
    "pops": r"common/history/pops",
    "buildings": r"common/history/buildings",
    "trade": r"common/history/trade",
}

# Game directories whose .txt files need keyword replacement (source → target)
# and whose output should be **aggregated** into a single ``state_merging.txt``
# file with ``REPLACE:`` prefixes.  These are game-script directories where
# only the modified entries need to override the base game.
REPLACE_KEYWORD_FILE_DIR = [
    "common/ai_strategies",
    "common/buildings",
    "common/character_templates",
    "common/country_creation",
    "common/country_definitions",
    "common/country_formation",
    "common/decisions",
    "common/dynamic_country_map_colors",
    "common/dynamic_country_names",
    "common/geographic_regions",
    "common/flag_definitions",
    "common/journal_entries",
    "common/mobilization_options",
    "common/political_movements",
    "common/scripted_buttons",
    "common/scripted_progress_bars",
]

# Game directories whose .txt files need keyword replacement (source → target)
# but whose output is written as **individual files** (one per input file)
# rather than aggregated.  These are typically data directories where each
# file stands alone and should be copied with substitutions applied.
REPLACE_COPY_FILE_DIR = [
    "common/coat_of_arms/template_lists",
    "common/company_types",
    "common/history/countries",
    "common/history/global",
    "common/history/diplomatic_plays",
    "common/history/military_formations",
    "common/on_actions",
    "common/scripted_effects",
    "common/scripted_triggers",
    "events",
    "events/agitators_events",
    "events/american_civil_war",
    "events/balkans_events",
    "events/brazil",
    "events/iberia_events",
    "events/india_events",
    "events/japan_events",
    "events/soi_events",
    "gfx/map/city_data/city_types",
]

# Game directories whose .txt files need **keyword removal** – any matched
# source state ID is deleted rather than replaced.  Output is aggregated
# into a single ``state_merging.txt`` with ``REPLACE:`` prefixes.
REMOVE_KEYWORD_FILE_DIR = ["common/strategic_regions"]

# Localization language codes mapped to their relative directory paths under
# the game root.
LOC_FILE_DIR = {
    "l_english": r"localization/english",
    "l_simp_chinese": r"localization/simp_chinese",
}

# Map-object locator categories and their corresponding game data filenames.
# Each key (``city``, ``farm``, …) maps to the file that defines map-pin
# positions for that hub type.
MAP_OBJECT_DATA_FILES = {
    "city": "generated_map_object_locators_city.txt",
    "farm": "generated_map_object_locators_farm.txt",
    "mine": "generated_map_object_locators_mine.txt",
    "port": "generated_map_object_locators_port.txt",
    "wood": "generated_map_object_locators_wood.txt",
}

# Hub names that are placeholders and should not be propagated to merged
# states.  ``"NAME"`` is the English placeholder; ``"名称"`` is the
# Simplified Chinese placeholder.
INVALID_HUB_NAMES = ["NAME", "名称"]


def _parse_merge(path, merge_levels: int = 0):
    """Parse all ``.txt`` files in *path* and merge them into a single Tree.

    Files are processed in sorted order so the result is deterministic.
    Non-``.txt`` files and sub-directories are silently skipped.

    Parameters
    ----------
    path : str
        Directory containing Paradox ``.txt`` files.
    merge_levels : int, optional
        Depth passed to :meth:`pyradox.Tree.merge`. ``0`` appends entries,
        including duplicates; higher values recursively combine tree values
        for that many levels before appending. This is not definition-level
        last-wins loading. Default is ``0``.

    Returns
    -------
    pyradox.Tree
        Combined tree representing the full directory contents.
    """

    result = pyradox.Tree()
    for filename in sorted(os.listdir(path)):
        # Skip non-.txt files
        if not filename.endswith(".txt"):
            continue
        fullpath = os.path.join(path, filename)
        if os.path.isfile(fullpath):
            # pyradox does not natively support Victoria 3, but Vic3 uses a
            # scripting language similar to HoI4, so game="HoI4" works here.
            tree = pyradox.parse_file(
                fullpath, game="HoI4", path_relative_to_game=False
            )
            result.merge(tree, merge_levels)
    return result


def _clean_v3_yml_numbered_keys(yml_path: str | os.PathLike) -> str:
    """Strip Vic3-style numbered keys from a localization YML file.

    Victoria 3 localization files use ``:0 "text"`` instead of the standard
    YAML ``: "text"`` syntax.  This function reads the raw file and converts
    all ``:<digits>`` prefixes to ``: `` so that :func:`yaml.safe_load` can
    parse the content.

    Parameters
    ----------
    yml_path : str
        Path to a Vic3 localization ``.yml`` file.

    Returns
    -------
    str
        The cleaned YML content suitable for :func:`yaml.safe_load`.
    """
    with open(yml_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    # Replace :<number> (optionally with spaces) before a quote or non-quote value
    cleaned = re.sub(r':\d+\s*"', ': "', raw)
    cleaned = re.sub(r':\d+\s+([^\n"]+)', r": \1", cleaned)
    return cleaned


def _prefix_replace(text: str) -> str:
    """Prefix ``REPLACE:`` on first-level assignment lines.

    This is required for aggregated mod files so that Victoria 3 treats the
    entries as overrides rather than additions.  The function is conservative:

    * Blank lines, comments, and indented lines are left as-is.
    * Lines already starting with ``REPLACE:`` are not double-prefixed.
    * Macro lines starting with ``@`` are skipped.

    Parameters
    ----------
    text : str
        Raw text of a Paradox ``.txt`` data file.

    Returns
    -------
    str
        Text with ``REPLACE:`` prepended to top-level assignment lines.
    """
    out = []
    for ln in text.splitlines(True):
        # skip empty lines, comments, indented lines, macros, and already-prefixed
        if not ln.strip() or ln.startswith(("#", " ", "\t", "REPLACE:", "@")):
            out.append(ln)
            continue
        # if the line contains an '=' assume it's a first-level assignment and prefix
        if "=" in ln:
            out.append("REPLACE:" + ln)
        else:
            out.append(ln)
    return "".join(out)


def _clear_output_dir(dir_path: str):
    """Remove all regular files in *dir_path*, creating it if necessary.

    Sub-directories are left untouched.  This is used to ensure the mod
    output directory is clean before writing new content.

    Parameters
    ----------
    dir_path : str
        Directory to clear.
    """
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        return
    for file in os.listdir(dir_path):
        if os.path.isdir(os.path.join(dir_path, file)):
            continue
        os.remove(os.path.join(dir_path, file))


def _build_keyword_pattern(merge_dict: dict):
    """Build a lookup table and compiled regex for keyword replacement.

    The merge dict maps *target* state IDs to lists of *source* state IDs
    that should be replaced by the target.  This function inverts that into
    a ``{source: target}`` lookup and compiles a word-boundary regex that
    matches any source key as a whole token.

    Keys are sorted longest-first so that longer identifiers are tried
    before shorter ones that might be substrings (e.g. ``STATE_MA``
    won't accidentally match inside ``STATE_MAIN``).

    Parameters
    ----------
    merge_dict : dict
        ``{target_state: [source_state, …]}`` mapping.

    Returns
    -------
    tuple[dict, re.Pattern | None]
        A ``(lookup, pattern)`` pair.  If *merge_dict* contains no source
        keys, *pattern* is ``None`` and *lookup* is empty.
    """
    lookup = {}
    for target, sources in merge_dict.items():
        for source in sources:
            lookup[source] = target

    if not lookup:
        return lookup, None

    keys = sorted(lookup.keys(), key=len, reverse=True)
    # Treat underscores as separators so tokens inside identifiers like
    # STATE_HIGHLANDS_state_name_assign are still replaced, but avoid
    # replacing state IDs that are part of compound state-region identifiers
    # like STATE_MAINE_ANJOU. Context validation is handled by the caller
    # using _keyword_replace() rather than the regex alone.
    pattern = re.compile(
        r"(?<![0-9A-Za-z])(" + "|".join(map(re.escape, keys)) + r")(?![0-9A-Za-z])"
    )
    return lookup, pattern


def _keyword_replace(match, lookup, text):
    """Regex replacement callback that replaces a matched source key with its target.

    Performs context-sensitive guarding to avoid replacing state IDs that
    appear inside compound state-region identifiers.  Specifically:

    * If the character **after** the match is ``_`` followed by an uppercase
      letter, the match is part of a compound like
      ``STATE_MAINE_ANJOU`` and is left unchanged.
    * If the character **before** the match is ``_`` preceded by an
      uppercase letter and the prefix matches the pattern
      ``STATE_[A-Z0-9_]*_``, the match is part of a compound state-region
      name and is left unchanged.

    Parameters
    ----------
    match : re.Match
        The regex match object for a source state ID.
    lookup : dict
        ``{source: target}`` mapping produced by
        :func:`_build_keyword_pattern`.
    text : str
        The full text being processed (needed for context inspection).

    Returns
    -------
    str
        The replacement target ID, or the original key if guarded.
    """
    key = match.group(1)
    start = match.start(1)
    end = match.end(1)
    if (
        end < len(text)
        and text[end] == "_"
        and end + 1 < len(text)
        and text[end + 1].isupper()
    ):
        return key
    if start >= 2 and text[start - 1] == "_" and text[start - 2].isupper():
        prefix = text[:start]
        if re.search(r"STATE_[A-Z0-9_]*_$", prefix):
            return key
    return lookup[key]


def _keyword_remove(match, lookup, text):
    """Regex replacement callback that **removes** a matched source key.

    Uses the same compound-identifier guarding logic as
    :func:`_keyword_replace`, but instead of substituting the target ID it
    returns an empty string, effectively deleting the reference.  This is
    used for directories like ``common/strategic_regions`` where consumed
    states should simply be removed.

    Parameters
    ----------
    match : re.Match
        The regex match object for a source state ID.
    lookup : dict
        ``{source: target}`` mapping (unused by remove, but kept for a
        consistent signature with :func:`_keyword_replace`).
    text : str
        The full text being processed.

    Returns
    -------
    str
        Empty string if the key should be removed, or the original key if
        guarded by compound-identifier context.
    """
    key = match.group(1)
    start = match.start(1)
    end = match.end(1)
    if (
        end < len(text)
        and text[end] == "_"
        and end + 1 < len(text)
        and text[end + 1].isupper()
    ):
        return key
    if start >= 2 and text[start - 1] == "_" and text[start - 2].isupper():
        prefix = text[:start]
        if re.search(r"STATE_[A-Z0-9_]*_$", prefix):
            return key
    return ""


def _iter_txt_files(base_game_dir: str):
    """Yield ``(filename, full_path)`` for each ``.txt`` file in *base_game_dir*.

    Non-``.txt`` files and sub-directories are skipped.  Returns silently if
    the directory does not exist.

    Parameters
    ----------
    base_game_dir : str
        Directory to scan.

    Yields
    ------
    tuple[str, str]
        ``(filename, absolute_path)`` for each matching file.
    """
    if not os.path.exists(base_game_dir):
        return
    for game_file in sorted(os.listdir(base_game_dir)):
        base_path = os.path.join(base_game_dir, game_file)
        if os.path.isdir(base_path):
            continue
        if not game_file.endswith(".txt"):
            continue
        yield game_file, base_path


def _write_text_file(output_file: str, text: str):
    """Write *text* to *output_file* using UTF-8 BOM encoding.

    Intermediate directories are created automatically if they do not exist.

    Parameters
    ----------
    output_file : str
        Destination file path.
    text : str
        Content to write.
    """
    if not os.path.exists(os.path.dirname(output_file)):
        os.makedirs(os.path.dirname(output_file))
    with open(output_file, "w", encoding="utf-8-sig") as f:
        f.write(text)


def _process_keyword_directory(
    base_game_dir: str,
    mod_dir: str,
    lookup: dict,
    pattern,
    transform,
    aggregate: bool = False,
):
    """Scan a game directory, apply keyword transformations, and write results.

    For each ``.txt`` file in *base_game_dir* that contains at least one
    match for *pattern*, the *transform* callback is applied to produce
    modified text.  Depending on *aggregate*, output is either written as
    individual files or concatenated into a single ``state_merging.txt``.

    Parameters
    ----------
    base_game_dir : str
        Path to the vanilla game directory to scan.
    mod_dir : str
        Path to the mod output directory.
    lookup : dict
        ``{source: target}`` mapping from :func:`_build_keyword_pattern`.
    pattern : re.Pattern | None
        Compiled regex for matching source state IDs.
    transform : callable
        ``transform(text, lookup, pattern) -> str`` – function that
        performs the actual substitution (replace or remove).
    aggregate : bool, optional
        If ``True``, all modified files are concatenated into a single
        output file ``state_merging.txt`` with ``REPLACE:`` prefixes on
        top-level entries.  If ``False``, each modified file is written
        individually.  Default is ``False``.
    """
    outputs = _keyword_outputs(
        _iter_txt_files(base_game_dir), lookup, pattern, transform, aggregate
    )
    for filename, text in outputs.items():
        _write_text_file(os.path.join(mod_dir, filename), text)


def _keyword_outputs(files, lookup, pattern, transform, aggregate=False):
    """Prepare modified files without writing or cleaning any output."""
    outputs = {}
    aggregated = []
    for filename, path in files:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
        if not pattern.search(text):
            continue
        logger.debug("Processing %s", path)
        modified = transform(text, lookup, pattern)
        if aggregate:
            aggregated.append(f"# ---- {filename} ----\n" + _prefix_replace(modified))
        else:
            outputs[filename] = modified
    if aggregated:
        outputs["state_merging.txt"] = "\n\n".join(aggregated)
    return outputs


class StateMerger:
    """Compose independent merge stages over ordered game-layout source roots.

    Construction never writes output or parses data. ``sources`` maps stage
    names to root lists, with later roots replacing matching relative filenames.
    Unspecified stages use ``game_root_dir``. Parsed-data attributes load lazily;
    every execution reloads fresh models. ``run`` defaults to all stages without
    injected compensation or bundled assets. The three legacy merge methods
    retain their original compensation and asset defaults.
    """

    def __init__(
        self,
        game_root_dir: str | os.PathLike,
        write_dir: str | os.PathLike,
        merge_dict: dict,
        cache_dir: str | os.PathLike = "./data",
        *,
        sources: Mapping[str, Sequence[str | os.PathLike]] | None = None,
    ):
        self.game_root_dir = game_root_dir
        self.write_dir = write_dir
        self.merge_dict = deepcopy(merge_dict)
        self.cache_dir = cache_dir
        self.base_game_dir = {
            key: os.path.join(game_root_dir, value)
            for key, value in STATE_FILE_DIR.items()
        }
        self.mod_dir = {
            key: os.path.join(write_dir, value) for key, value in STATE_FILE_DIR.items()
        }
        self._resolver = SourceResolver(game_root_dir, sources)
        self._models: dict[str, Any] = {}
        self._core_files: dict[str, dict[str, Path]] = {}
        self._core_trees: dict[str, dict[str, Any]] = {}

    def _load_model(self, stage):
        if stage not in self._models:
            self._resolver.validate([stage])
            files = self._resolver.files(stage, STATE_FILE_DIR[stage])
            if not files:
                raise ValueError(
                    f"{stage}: no .txt input files in {STATE_FILE_DIR[stage]}; "
                    f"searched roots: {self._resolver.describe(stage)}"
                )
            trees = {}
            combined = pyradox.Tree()
            try:
                for name, path in files.items():
                    tree = pyradox.parse_file(
                        str(path), game="HoI4", path_relative_to_game=False
                    )
                    trees[name] = tree
                    combined.merge(tree, 1 if stage == "map_data" else 2)
                model_type = {
                    "map_data": StateRegion,
                    "state": States,
                    "pops": Pops,
                    "buildings": Buildings,
                    "trade": Trade,
                }[stage]
                self._models[stage] = model_type(combined if len(combined) else None)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ValueError(
                    f"{stage}: cannot load inputs from {self._resolver.describe(stage)}: {exc}"
                ) from exc
            self._core_files[stage] = files
            self._core_trees[stage] = trees
        return self._models[stage]

    @property
    def map_data(self) -> StateRegion:
        return self._load_model("map_data")

    @map_data.setter
    def map_data(self, value):
        self._models["map_data"] = value

    @property
    def states(self) -> States:
        return self._load_model("state")

    @states.setter
    def states(self, value):
        self._models["state"] = value

    @property
    def pops(self) -> Pops:
        return self._load_model("pops")

    @pops.setter
    def pops(self, value):
        self._models["pops"] = value

    @property
    def buildings(self) -> Buildings:
        return self._load_model("buildings")

    @buildings.setter
    def buildings(self, value):
        self._models["buildings"] = value

    @property
    def trade(self) -> Trade:
        return self._load_model("trade")

    @trade.setter
    def trade(self, value):
        self._models["trade"] = value

    def _validate_plan(self):
        if not isinstance(self.merge_dict, dict):
            raise TypeError(
                "Merge plan must be an object mapping targets to source lists"
            )
        consumed = set()
        active_targets = set()
        for target, foods in self.merge_dict.items():
            if not isinstance(target, str) or not target or not isinstance(foods, list):
                raise ValueError(
                    "Merge plan requires nonempty target names and source lists"
                )
            if foods:
                active_targets.add(target)
            for food in foods:
                if not isinstance(food, str) or not food or food == target:
                    raise ValueError(f"Invalid source state for {target}: {food!r}")
                if food in consumed:
                    raise ValueError(f"Source state appears more than once: {food}")
                consumed.add(food)
        if active_targets & consumed:
            raise ValueError(
                "Merge targets cannot also be consumed states (chained merges)"
            )

    def run(
        self,
        stages=STAGES,
        *,
        integration_traits: bool = False,
        assets=(),
        ignore_small_states: bool = False,
        small_state_limit: int = 4,
    ) -> None:
        """Prepare all selected outputs before clearing their directories.

        ``map_objects`` and ``localization`` read/project ``map_data`` without
        emitting it. Missing history entries are allowed for sparse datasets;
        map references must exist. Selected directories lose existing regular
        files; disabled stages and unrelated asset files remain untouched.
        """
        selected = validate_names(stages, STAGES, "stages")
        requested_assets = set(validate_names(assets, ASSETS, "assets"))
        if not isinstance(integration_traits, bool):
            raise TypeError("integration_traits must be a boolean")
        if not isinstance(small_state_limit, int) or small_state_limit < 0:
            raise ValueError("small_state_limit must be a nonnegative integer")
        self._validate_plan()
        needed = set(selected)
        if needed & {"map_objects", "localization"}:
            needed.add("map_data")
        ordered_needed = [stage for stage in STAGES if stage in needed]
        logger.info("Selected merge stages: %s", ", ".join(selected))
        self._resolver.validate(ordered_needed)
        self._resolver.check_destination(self.write_dir, STAGES)
        previous_map = self._models.get("map_data")
        for stage in needed & STATE_FILE_DIR.keys():
            self._models.pop(stage, None)
            self._core_files.pop(stage, None)
            self._core_trees.pop(stage, None)
        outputs: dict[str, str] = {}
        clear_dirs: list[str] = []
        original_map_data = {}
        if "map_data" in needed:
            regions = self.map_data
            for target, foods in self.merge_dict.items():
                for name in [target, *foods]:
                    if name not in regions or regions[name].is_sea_node():
                        raise ValueError(
                            f"map_data: merge reference is missing or a sea node: {name}; "
                            f"searched roots: {self._resolver.describe('map_data')}"
                        )
            original_map_data = {
                name: {
                    attr: getattr(region, attr)
                    for attr in ("id", *MAP_OBJECT_DATA_FILES)
                }
                for name, region in regions.items()
            }
            regions.merge_states(
                {target: foods for target, foods in self.merge_dict.items() if foods},
                ignoreSmallStates=ignore_small_states,
                smallStateLimit=small_state_limit,
                integration_traits=integration_traits,
            )
        for stage in STAGES:
            if stage not in selected:
                continue
            if stage in STATE_FILE_DIR:
                logger.info("Merging %s data", stage)
                model = self._load_model(stage)
                if stage != "map_data":
                    try:
                        model.merge_states(self.merge_dict)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(
                            f"{stage}: invalid merge references/data in "
                            f"{self._resolver.describe(stage)}: {exc}"
                        ) from exc
                outputs.update(self._core_outputs(stage))
                clear_dirs.append(STATE_FILE_DIR[stage])
            elif stage == "map_objects":
                outputs.update(self._map_object_outputs(original_map_data))
                clear_dirs.append("gfx/map/map_object_data")
            elif stage == "misc":
                logger.info("Processing miscellaneous files")
                misc_outputs, directories = self._misc_outputs()
                outputs.update(misc_outputs)
                clear_dirs.extend(directories)
            elif stage == "localization":
                logger.info("Processing localization")
                outputs.update(self._localization_outputs())
                clear_dirs.extend(LOC_FILE_DIR.values())
        if integration_traits:
            requested_assets.add("state_traits")
        outputs.update(self._asset_outputs(requested_assets))
        # All parsing, reference validation, transformations and serialization have
        # succeeded. Only selected stages own broad directory cleanup.
        for relative_dir in dict.fromkeys(clear_dirs):
            logger.info("Clearing selected output directory: %s", relative_dir)
            _clear_output_dir(os.path.join(self.write_dir, relative_dir))
        for relative_file, text in sorted(outputs.items()):
            _write_text_file(os.path.join(self.write_dir, relative_file), text)
        if "map_data" not in selected and previous_map is not None:
            # A read-only dependency must not replace the last exposed map
            # result, which callers may inspect after the legacy pipeline.
            self._models["map_data"] = previous_map

    def _core_outputs(self, stage):
        directory = STATE_FILE_DIR[stage]
        filename = {
            "map_data": "state_merging.txt",
            "state": "00_states.txt",
            "pops": "state_merging.txt",
            "buildings": "state_merging.txt",
            "trade": "00_historical_trade.txt",
        }[stage]
        outputs = {}
        sea_names = set()
        for name in self._core_files[stage]:
            if stage == "map_data":
                entries = self._core_trees[stage][name].to_python()
                land = any("subsistence_building" in data for data in entries.values())
                # Pure sea files continue to be inherited, except when their
                # filename is also our generated filename and will be replaced.
                if entries and not land and name != filename:
                    continue
                sea_names.update(
                    key
                    for key, data in entries.items()
                    if "subsistence_building" not in data
                )
            if name != filename:
                outputs[f"{directory}/{name}"] = ""
        if stage == "map_data":
            text = "".join(
                str(region)
                for name, region in self.map_data.items()
                if not region.is_sea_node() or name in sea_names
            )
        else:
            text = str(self._models[stage])
        outputs[f"{directory}/{filename}"] = text
        return outputs

    def merge_state_data(
        self, ignoreSmallStates: bool = False, smallStateLimit: int = 4
    ):
        """Legacy core/map-object pipeline, including integration compensation."""
        self.run(
            stages=(*STATE_FILE_DIR, "map_objects"),
            integration_traits=True,
            ignore_small_states=ignoreSmallStates,
            small_state_limit=smallStateLimit,
        )

    def merge_misc_data(self):
        """Legacy miscellaneous pipeline, including the two USA overrides."""
        self.run(stages=["misc"], assets=["usa_flag", "usa_state_counter"])

    def merge_loc_data(self):
        """Legacy localization pipeline; computes its map dependency internally."""
        self.run(stages=["localization"])

    def _misc_outputs(self):
        outputs = {}
        directories = []
        lookup, pattern = _build_keyword_pattern(self.merge_dict)
        groups = (
            (REPLACE_COPY_FILE_DIR, False, _keyword_replace),
            (REPLACE_KEYWORD_FILE_DIR, True, _keyword_replace),
            (REMOVE_KEYWORD_FILE_DIR, True, _keyword_remove),
        )
        for relatives, aggregate, callback in groups:
            for relative in relatives:
                directories.append(relative)
                files = self._resolver.files("misc", relative)
                if pattern is None:
                    continue
                transformed = _keyword_outputs(
                    files.items(),
                    lookup,
                    pattern,
                    lambda text, lookup, pattern, callback=callback: pattern.sub(
                        lambda match: callback(match, lookup, text), text
                    ),
                    aggregate,
                )
                outputs.update(
                    {f"{relative}/{name}": text for name, text in transformed.items()}
                )
        return outputs, directories

    def _localization_outputs(self):
        outputs = {}
        for lang, directory in LOC_FILE_DIR.items():
            data = {}
            files = self._resolver.files(
                "localization", directory, ".yml", by_layer=True
            )
            for path in files.values():
                # Vic3 localization is not general YAML: unrelated flavor text
                # may contain unescaped quotes. Only hub names are consumed by
                # this stage, so do not parse unrelated localization values.
                cleaned = _clean_v3_yml_numbered_keys(path)
                relevant = "\n".join(
                    re.sub(
                        r'"(?:\\.|[^"\\])*"|#[^\n]*|\t',
                        lambda match: (
                            " "
                            if match[0] == "\t"
                            else ""
                            if match[0].startswith("#")
                            else match[0]
                        ),
                        line,
                    )
                    for line in cleaned.splitlines()
                    if re.match(r"^\s*(?:l_[a-z_]+|HUB_NAME_[A-Za-z0-9_]+)\s*:", line)
                )
                try:
                    parsed = yaml.safe_load(relevant)
                except yaml.YAMLError as exc:
                    raise ValueError(
                        f"localization: invalid hub entries in {path}: {exc}"
                    ) from exc
                if parsed is None:
                    continue
                if (
                    isinstance(parsed, dict)
                    and parsed.get(lang) is None
                    and lang in parsed
                ):
                    continue  # A header-only language file has no hub entries.
                if not isinstance(parsed, dict) or not isinstance(
                    parsed.get(lang), dict
                ):
                    raise TypeError(f"localization: expected {lang} mapping in {path}")
                data.update(parsed[lang])
            missing = {}
            for diner, food_list in self.merge_dict.items():
                if not food_list:
                    continue
                for attr in MAP_OBJECT_DATA_FILES:
                    if not getattr(self.map_data[diner], attr):
                        continue
                    key = f"HUB_NAME_{diner}_{attr}"
                    if key in data:
                        continue
                    for food in food_list:
                        value = data.get(f"HUB_NAME_{food}_{attr}")
                        if value and value not in INVALID_HUB_NAMES:
                            missing[key] = str(value)
                            logger.debug("Inherited localization: %s", value)
                            break
            if missing:
                # JSON-quoted scalars also form valid Vic3 localization values;
                # this preserves apostrophes and embedded double quotes.
                lines = [f"{lang}:"] + [
                    f" {key}:0 {json.dumps(value, ensure_ascii=False)}"
                    for key, value in sorted(missing.items())
                ]
                outputs[f"{directory}/hub_names_states_merging_{lang}.yml"] = (
                    "\n".join(lines) + "\n"
                )
        return outputs

    @staticmethod
    def _asset_outputs(assets):
        definitions = {
            "state_traits": (
                "common/state_traits/state_merging.txt",
                vic3_state_merger.assets.state_traits.CONTENT,
            ),
            "usa_flag": (
                "common/flag_definitions/state_merging_flag_definition_usa.txt",
                vic3_state_merger.assets.flag_definitions_usa.CONTENT,
            ),
            "usa_state_counter": (
                "common/script_values/state_merging_usa_state_counter.txt",
                vic3_state_merger.assets.usa_state_counter.CONTENT,
            ),
        }
        return dict(definitions[name] for name in sorted(assets))

    def copy_state_data(self):
        """Cache resolved core files, retaining the legacy example/sea exclusions."""
        self._copy_resolved(STATE_FILE_DIR, "game_file")

    def copy_map_object_data(self):
        """Cache winning locator files; absent optional locators are skipped."""
        self._copy_resolved({"map_objects": "gfx/map/map_object_data"}, "game_file")

    def _copy_resolved(self, directories, prefix):
        self._resolver.validate(directories)
        self._resolver.check_destination(self.cache_dir, directories)
        for stage, relative in directories.items():
            for name, source in self._resolver.files(stage, relative).items():
                if stage == "map_objects":
                    if name not in MAP_OBJECT_DATA_FILES.values():
                        continue
                    category = "map_object_data"
                else:
                    if "99_seas" in name or "100_pops_example" in name:
                        continue
                    category = stage
                target = Path(self.cache_dir) / prefix / category / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

    def _map_object_outputs(self, original_map_data):
        """Retarget and clean up map-object locator instances for merged states.

        When states merge, the surviving (diner) state may not have a
        locator for every hub type (city, farm, mine, port, wood).  This
        method finds the best available locator from the consumed (food)
        states and retargets its instance to the diner's state ID.  All
        locator instances belonging to consumed states are then removed.

        Parameters
        ----------
        original_map_data : dict[str, dict[str, str | int]]
            Snapshot of each state's ID and hub assignments taken before
            merging (from :attr:`map_data`).
        """
        outputs = {}
        directory = "gfx/map/map_object_data"
        files = self._resolver.files("map_objects", directory)
        for file in MAP_OBJECT_DATA_FILES.values():
            base_game_file = files.get(file)
            if base_game_file is None:
                continue

            # pyradox does not natively support Victoria 3, but Vic3 uses a
            # scripting language similar to HoI4, so game="HoI4" works here.
            parser = pyradox.parse_file(
                str(base_game_file), game="HoI4", path_relative_to_game=False
            )
            if isinstance(parser, pyradox.Tree) and not len(parser):
                outputs[f"{directory}/{file}"] = ""
                continue
            # Some map-object files wrap the tree in a list; unwrap if needed
            if not isinstance(parser, pyradox.Tree):
                parser = parser[0]

            map_object_data = MapObjectData(parser)
            for diner, food_list in self.merge_dict.items():
                diner_data = original_map_data.get(diner)
                if not diner_data:
                    continue

                locator_attr = None
                for attr, locator_file in MAP_OBJECT_DATA_FILES.items():
                    if locator_file == file:
                        locator_attr = attr
                        break

                if locator_attr is None:
                    continue

                source_ids = [int(diner_data["id"])]
                for food in food_list:
                    food_data = original_map_data.get(food)
                    if food_data is not None:
                        source_ids.append(int(food_data["id"]))

                # Determine which state provides the locator for this hub type.
                # Prefer the diner's own locator; fall back to the first food
                # state that has one.
                diner_has_locator = bool(diner_data.get(locator_attr, ""))
                target_id = int(diner_data["id"])
                source_id = target_id

                if not diner_has_locator:
                    for food in food_list:
                        food_data = original_map_data.get(food)
                        if food_data and food_data.get(locator_attr, ""):
                            source_id = int(food_data["id"])
                            break

                if source_id != target_id:
                    # Retarget: move the locator instance from the food state
                    # to the diner state so the map pin appears correctly.
                    map_object_data.retarget_instance_id(source_id, target_id)

                # Remove locator instances for all states that no longer exist
                # after merging.  If we retargeted from a food state, keep its
                # instance (it now belongs to the diner); remove all others.
                removal_ids = {
                    state_id for state_id in source_ids if state_id != target_id
                }
                if source_id != target_id:
                    removal_ids.discard(source_id)
                if removal_ids:
                    map_object_data.remove_instances_by_id(removal_ids)

            outputs[f"{directory}/{file}"] = str(map_object_data)
        return outputs
