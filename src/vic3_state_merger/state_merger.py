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

import os
import re
import copy
import yaml
import shutil
import pyradox
import vic3_state_merger.assets.flag_definitions_usa
import vic3_state_merger.assets.state_traits
import vic3_state_merger.assets.usa_state_counter
from vic3_state_merger.map_object_data import MapObjectData
from vic3_state_merger.state_regions import StateRegion
from vic3_state_merger.buildings import Buildings
from vic3_state_merger.pops import Pops
from vic3_state_merger.states import States
from vic3_state_merger.trade import Trade

try:
    from importlib.resources import files, as_file
except ImportError:  # Python 3.8 / 3.7
    from importlib_resources import files, as_file  # pyright: ignore[reportMissingImports]

# Mapping of logical category names to relative paths under the game root.
# Each key corresponds to one of the five core data categories parsed and
# merged by :class:`StateMerger`.
state_file_dir = {
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
replace_keyword_file_dir = [
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
replace_copy_file_dir = [
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
remove_keyword_file_dir = ["common/strategic_regions"]

# Localization language codes mapped to their relative directory paths under
# the game root.
loc_file_dir = {
    "l_english": r"localization/english",
    "l_simp_chinese": r"localization/simp_chinese",
}

# Map-object locator categories and their corresponding game data filenames.
# Each key (``city``, ``farm``, …) maps to the file that defines map-pin
# positions for that hub type.
map_object_data_files = {
    "city": "generated_map_object_locators_city.txt",
    "farm": "generated_map_object_locators_farm.txt",
    "mine": "generated_map_object_locators_mine.txt",
    "port": "generated_map_object_locators_port.txt",
    "wood": "generated_map_object_locators_wood.txt",
}

# Hub names that are placeholders and should not be propagated to merged
# states.  ``"NAME"`` is the English placeholder; ``"名称"`` is the
# Simplified Chinese placeholder.
invalid_hub_names = ["NAME", "名称"]


def _parse_merge(path, merge_levels: int = 0):
    """Parse all ``.txt`` files in *path* and merge them into a single Tree.

    Files are processed in sorted order so the result is deterministic.
    Non-``.txt`` files and sub-directories are silently skipped.

    Parameters
    ----------
    path : str
        Directory containing Paradox ``.txt`` files.
    merge_levels : int, optional
        Depth passed to :meth:`pyradox.Tree.merge`.  ``0`` keeps all keys
        (appending duplicates), ``1`` overwrites at the first level, ``2``
        overwrites at the first two levels, etc.  Default is ``0``.

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


def _clean_v3_yml_numbered_keys(yml_path: str) -> str:
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
        if (
            not ln.strip()
            or ln.startswith("#")
            or ln.startswith((" ", "\t"))
            or ln.startswith("REPLACE:")
            or ln.startswith("@")
        ):
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
    for game_file in os.listdir(base_game_dir):
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
    if not os.path.exists(base_game_dir):
        return

    aggregated = []
    for game_file, base_path in _iter_txt_files(base_game_dir):
        with open(base_path, "r", encoding="utf-8-sig") as f:
            text = f.read()

        if not pattern.search(text):
            continue

        print("Processing", base_path)
        modified = transform(text, lookup, pattern)
        if aggregate:
            modified = _prefix_replace(modified)
            aggregated.append(f"# ---- {game_file} ----\n" + modified)
        else:
            output_file = os.path.join(mod_dir, game_file)
            print("Writing modified copy to", output_file)
            _write_text_file(output_file, modified)

    if aggregate and aggregated:
        output_file = os.path.join(mod_dir, "state_merging.txt")
        print("Writing aggregated output to", output_file)
        _write_text_file(output_file, "\n\n".join(aggregated))


class StateMerger:
    """Orchestrates the full Victoria 3 state-merge pipeline.

    A *merge dict* defines which states are consumed ("food") and which
    state survives ("diner").  For each merge, the diner absorbs the food's
    territory, buildings, population, trade routes, and map pins, while the
    food's data is discarded.

    The class parses the five core data categories at construction time and
    exposes three public methods that should be called in order:

    1. :meth:`merge_state_data` – merge core state data and map objects.
    2. :meth:`merge_misc_data` – keyword replacement across misc game files.
    3. :meth:`merge_loc_data` – patch localization hub names.

    Additionally, :meth:`copy_state_data` and :meth:`copy_map_object_data`
    can be used to cache vanilla files for later comparison.

    Parameters
    ----------
    game_root_dir : str
        Path to the Victoria 3 installation directory (containing
        ``common/``, ``map_data/``, etc.).
    write_dir : str
        Path to the mod output directory.  Merged files are written here,
        mirroring the game's directory structure.
    merge_dict : dict
        ``{target_state: [source_state, …]}`` mapping.  Each key is a diner
        state; its value is the list of food states to merge into it.
    cache_dir : str, optional
        Directory used for caching vanilla game files.  Defaults to
        ``"./data"``.

    Attributes
    ----------
    map_data : StateRegion
        Parsed state-region (map) data.
    buildings : Buildings
        Parsed buildings data.
    pops : Pops
        Parsed population data.
    states : States
        Parsed state history data.
    trade : Trade
        Parsed trade route data.
    """

    def __init__(
        self,
        game_root_dir: str,
        write_dir: str,
        merge_dict: dict,
        cache_dir: str = "./data",
    ):
        self.base_game_dir = {}
        self.mod_dir = {}
        self.game_root_dir = game_root_dir
        self.write_dir = write_dir
        self.merge_dict = merge_dict
        self.cache_dir = cache_dir

        # Set the base game and mod directories
        for key, value in state_file_dir.items():
            self.base_game_dir[key] = os.path.join(game_root_dir, value)
            self.mod_dir[key] = os.path.join(write_dir, value)
            _clear_output_dir(self.mod_dir[key])

        # Parse State Regions data (merge_levels=1 because map_data files
        # have top-level keys that should overwrite rather than append)
        parser = _parse_merge(self.base_game_dir["map_data"], merge_levels=1)
        self.map_data = StateRegion(parser)

        # Parse Buildings, Pops, States, and Trade data (merge_levels=2
        # because these files nest state entries under a second-level key
        # and we want per-state overwrites at that depth)
        parser = _parse_merge(self.base_game_dir["buildings"], merge_levels=2)
        self.buildings = Buildings(parser)
        parser = _parse_merge(self.base_game_dir["pops"], merge_levels=2)
        self.pops = Pops(parser)
        parser = _parse_merge(self.base_game_dir["state"], merge_levels=2)
        self.states = States(parser)
        parser = _parse_merge(self.base_game_dir["trade"], merge_levels=2)
        self.trade = Trade(parser)

    def merge_state_data(
        self, ignoreSmallStates: bool = False, smallStateLimit: int = 4
    ):
        """Merge the five core data categories and map-object data.

        This method performs the following steps in order:

        1. Snapshots the original map data (IDs and hub assignments) so
           map-object locators can be retargeted later.
        2. Clears all output files in the mod directory so that only merged
           data is present (vanilla entries for consumed states must not
           persist).
        3. Merges each core category (map regions, buildings, pops, states,
           trade) and writes the results.
        4. Retargets map-object locator instances for merged states.
        5. Writes the bundled state-traits override file.

        Parameters
        ----------
        ignoreSmallStates : bool, optional
            If ``True``, states with fewer provinces than *smallStateLimit*
            are skipped during map-region merging.  Default ``False``.
        smallStateLimit : int, optional
            Minimum number of provinces a state must have to be considered
            for merging when *ignoreSmallStates* is ``True``.  Default ``4``.
        """
        original_map_data = {
            state_name: {
                "id": state.id,
                "city": state.city,
                "farm": state.farm,
                "mine": state.mine,
                "port": state.port,
                "wood": state.wood,
            }
            for state_name, state in self.map_data.items()
        }
        # Blank out every existing .txt file in each output category so that
        # only the merged data (written below) remains.  Without this step,
        # vanilla entries for consumed states would persist alongside the
        # merged output.
        for key, value in self.base_game_dir.items():
            for file in os.listdir(value):
                if file == "state_merging.txt":
                    continue
                with open(
                    os.path.join(self.mod_dir[key], file), "w", encoding="utf-8-sig"
                ) as file:
                    file.write("")
        # Remove the seas file – it should not be overridden by the mod
        if os.path.exists(os.path.join(self.mod_dir["map_data"], "99_seas.txt")):
            os.remove(os.path.join(self.mod_dir["map_data"], "99_seas.txt"))

        # Merge map_data
        id_dict = self.map_data.merge_states(
            self.merge_dict,
            ignoreSmallStates=ignoreSmallStates,
            smallStateLimit=smallStateLimit,
        )
        self.map_data.dump(os.path.join(self.mod_dir["map_data"], "state_merging.txt"))
        # Merge buildings
        self.buildings.merge_states(self.merge_dict)
        self.buildings.dump(
            os.path.join(self.mod_dir["buildings"], "state_merging.txt")
        )
        # Merge pops
        self.pops.merge_states(self.merge_dict)
        self.pops.dump(os.path.join(self.mod_dir["pops"], "state_merging.txt"))
        # Merge states
        self.states.merge_states(self.merge_dict)
        self.states.dump(os.path.join(self.mod_dir["state"], "00_states.txt"))
        # Merge trade
        self.trade.merge_states(self.merge_dict)
        self.trade.dump(os.path.join(self.mod_dir["trade"], "00_historical_trade.txt"))
        # Merge map_object_data
        self._merge_map_object_data(id_dict, original_map_data)

        # Write the bundled state-traits override (replaces merged states'
        # trait lists to account for changed province counts).
        dir = os.path.join(self.write_dir, "common", "state_traits")
        file_str = vic3_state_merger.assets.state_traits.str
        if not os.path.exists(dir):
            os.makedirs(dir)
        if os.path.exists(os.path.join(dir, "state_merging.txt")):
            os.remove(os.path.join(dir, "state_merging.txt"))
        with open(
            os.path.join(dir, "state_merging.txt"), "w", encoding="utf-8-sig"
        ) as file:
            file.write(file_str)

    def _merge_map_object_data(
        self,
        id_dict: dict[int, list[int]],
        original_map_data: dict[str, dict[str, str | int]],
    ):
        """Retarget and clean up map-object locator instances for merged states.

        When states merge, the surviving (diner) state may not have a
        locator for every hub type (city, farm, mine, port, wood).  This
        method finds the best available locator from the consumed (food)
        states and retargets its instance to the diner's state ID.  All
        locator instances belonging to consumed states are then removed.

        Parameters
        ----------
        id_dict : dict[int, list[int]]
            Mapping from diner state ID to the list of food state IDs
            produced by :meth:`StateRegion.merge_states`.
        original_map_data : dict[str, dict[str, str | int]]
            Snapshot of each state's ID and hub assignments taken before
            merging (from :attr:`map_data`).
        """
        output_dir = os.path.join(self.write_dir, "gfx", "map", "map_object_data")
        _clear_output_dir(output_dir)

        for file in map_object_data_files.values():
            base_game_file = os.path.join(
                self.game_root_dir, "gfx", "map", "map_object_data", file
            )
            if not os.path.exists(base_game_file):
                continue

            # pyradox does not natively support Victoria 3, but Vic3 uses a
            # scripting language similar to HoI4, so game="HoI4" works here.
            parser = pyradox.parse_file(
                base_game_file, game="HoI4", path_relative_to_game=False
            )
            # Some map-object files wrap the tree in a list; unwrap if needed
            if not isinstance(parser, pyradox.Tree):
                parser = parser[0]

            map_object_data = MapObjectData(parser)
            for diner, food_list in self.merge_dict.items():
                diner_data = original_map_data.get(diner)
                if not diner_data:
                    continue

                locator_attr = None
                for attr, locator_file in map_object_data_files.items():
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

            _write_text_file(os.path.join(output_dir, file), str(map_object_data))

    def merge_misc_data(self):
        """Apply keyword replacement and removal across miscellaneous game directories.

        Three categories of directories are processed:

        * **Copy-replace directories** – individual files are copied with
          source→target keyword substitution.
        * **Aggregated-replace directories** – matching entries are
          extracted, substituted, prefixed with ``REPLACE:``, and
          aggregated into a single ``state_merging.txt``.
        * **Aggregated-remove directories** – same as above, but matched
          source keys are deleted rather than replaced.

        After keyword processing, bundled asset overrides for the USA flag
        definitions and USA state counter are written to the mod directory.
        """
        # Phase 1: Copy-replace directories – write individual modified files
        for dir in replace_copy_file_dir:
            base_game_dir = os.path.join(self.game_root_dir, dir)
            mod_dir = os.path.join(self.write_dir, dir)
            print("Scanning", base_game_dir)
            _clear_output_dir(mod_dir)
            lookup, pattern = _build_keyword_pattern(self.merge_dict)
            if not lookup or pattern is None:
                continue

            _process_keyword_directory(
                base_game_dir,
                mod_dir,
                lookup,
                pattern,
                lambda text, lookup, pattern: pattern.sub(
                    lambda m: _keyword_replace(m, lookup, text), text
                ),
            )

        # Phase 2: Aggregated-replace directories – merge into state_merging.txt
        for dir in replace_keyword_file_dir:
            base_game_dir = os.path.join(self.game_root_dir, dir)
            mod_dir = os.path.join(self.write_dir, dir)
            print("Scanning", base_game_dir)

            _clear_output_dir(mod_dir)
            lookup, pattern = _build_keyword_pattern(self.merge_dict)
            if not lookup or pattern is None:
                continue

            _process_keyword_directory(
                base_game_dir,
                mod_dir,
                lookup,
                pattern,
                lambda text, lookup, pattern: pattern.sub(
                    lambda m: _keyword_replace(m, lookup, text), text
                ),
                aggregate=True,
            )

        # Phase 3: Aggregated-remove directories – delete matched keys
        for dir in remove_keyword_file_dir:
            base_game_dir = os.path.join(self.game_root_dir, dir)
            mod_dir = os.path.join(self.write_dir, dir)
            print("Scanning", base_game_dir)

            _clear_output_dir(mod_dir)
            lookup, pattern = _build_keyword_pattern(self.merge_dict)
            if not lookup or pattern is None:
                continue

            _process_keyword_directory(
                base_game_dir,
                mod_dir,
                lookup,
                pattern,
                lambda text, lookup, pattern: pattern.sub(
                    lambda m: _keyword_remove(m, lookup, text), text
                ),
                aggregate=True,
            )

        # Copy USA flag adaptation file to mod directory
        dir = os.path.join(self.write_dir, "common", "flag_definitions")
        file_str = vic3_state_merger.assets.flag_definitions_usa.str
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(os.path.join(dir, "state_merging_flag_definition_usa.txt")):
            os.remove(os.path.join(dir, "state_merging_flag_definition_usa.txt"))
        with open(
            os.path.join(dir, "state_merging_flag_definition_usa.txt"),
            "w",
            encoding="utf-8-sig",
        ) as file:
            file.write(file_str)

        # Copy USA state counting file to mod directory
        dir = os.path.join(self.write_dir, "common", "script_values")
        file_str = vic3_state_merger.assets.usa_state_counter.str
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(os.path.join(dir, "state_merging_usa_state_counter.txt")):
            os.remove(os.path.join(dir, "state_merging_usa_state_counter.txt"))
        with open(
            os.path.join(dir, "state_merging_usa_state_counter.txt"),
            "w",
            encoding="utf-8-sig",
        ) as file:
            file.write(file_str)

    def merge_loc_data(self):
        """Patch localization hub-name files for merged states.

        When a diner state absorbs food states, it may gain new hub types
        (e.g. a port or mine) that it did not have before.  This method
        checks whether the diner's hub names exist in the localization
        data and, if missing, copies the name from the first food state
        that provides a valid (non-placeholder) name.

        Output is written as per-language YML files
        (``hub_names_states_merging_<lang>.yml``) in the mod directory.
        """
        # Read localization yml files
        for lang, loc_dir in loc_file_dir.items():
            print(f"Reading localization files for {lang}...")
            hub_file = os.path.join(
                self.game_root_dir, loc_dir, f"hub_names_{lang}.yml"
            )
            miss_dict = {}
            with open(hub_file, "r", encoding="utf-8-sig") as f:
                cleaned_yml = _clean_v3_yml_numbered_keys(hub_file)
                data = yaml.safe_load(cleaned_yml)[lang]
                # Process the localization data as needed
                print(f"Processing {hub_file} for {lang}")
                for diner, food_list in self.merge_dict.items():
                    # Skip states with empty food lists (no merging needed)
                    if not food_list:
                        continue

                    # Check if the diner state exists in map data
                    if diner not in self.map_data:
                        print(
                            f"Warning: {diner} not found in map data, skipping localization processing"
                        )
                        continue

                    # Check each hub type the diner has on the map; if its
                    # localization key is missing, try to inherit from a food.
                    for attr in ["city", "wood", "mine", "farm", "port"]:
                        # Skip hub types the diner doesn't possess on the map
                        if getattr(self.map_data[diner], attr, "") == "":
                            continue
                        if f"HUB_NAME_{diner}_{attr}" in data.keys():
                            continue
                        # If not found, add a missing hub name entry
                        print(f"Missing HUB_NAME_{diner}_{attr} in {lang}")
                        # Search for attribute in the food_list
                        for food in food_list:
                            if f"HUB_NAME_{food}_{attr}" in data.keys():
                                if data[f"HUB_NAME_{food}_{attr}"] in invalid_hub_names:
                                    continue
                                # Wrap the value in double quotes so PyYAML
                                # emits it as a plain scalar rather than adding
                                # its own quoting style.
                                miss_dict[f"HUB_NAME_{diner}_{attr}"] = (
                                    '"' + data[f"HUB_NAME_{food}_{attr}"] + '"'
                                )
                                print(miss_dict[f"HUB_NAME_{diner}_{attr}"])
                                break
            # Write the missing hub names to the localization file
            write_file = os.path.join(
                self.write_dir, loc_dir, f"hub_names_states_merging_{lang}.yml"
            )
            if miss_dict:
                print(f"Modifying {write_file}")
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(write_file)):
                    os.makedirs(os.path.dirname(write_file))
                with open(write_file, "w", encoding="utf-8-sig") as f:
                    content = yaml.dump(
                        {lang: miss_dict},
                        allow_unicode=True,
                        default_style="",
                        default_flow_style=False,
                    )
                    # Remove single quotes inserted by PyYAML – Vic3 expects
                    # unquoted or double-quoted values in localization YML.
                    content = content.replace("'", "")
                    f.write(content)

    def copy_state_data(self):
        """Cache vanilla state data files to the cache directory.

        Each ``.txt`` file from the five core data directories is copied
        to ``<cache_dir>/game_file/<category>/``.  Files containing
        ``99_seas`` or ``100_pops_example`` in their name are skipped.
        This is useful for diffing the mod output against the vanilla data.
        """
        for key in state_file_dir.keys():
            for file in os.listdir(self.base_game_dir[key]):
                if "99_seas" in file or "100_pops_example" in file:
                    continue
                base_game_file = os.path.join(self.base_game_dir[key], file)
                # copy to cache dir
                cache_file = os.path.join(self.cache_dir, "game_file", key, file)
                if not os.path.exists(os.path.dirname(cache_file)):
                    os.makedirs(os.path.dirname(cache_file))
                shutil.copy(base_game_file, cache_file)

    def copy_map_object_data(self):
        """Cache vanilla map-object locator files to the cache directory.

        Each locator file listed in :data:`map_object_data_files` is copied
        to ``<cache_dir>/game_file/map_object_data/``.
        """
        for file in map_object_data_files.values():
            base_game_file = os.path.join(
                self.game_root_dir, "gfx", "map", "map_object_data", file
            )
            # copy to cache dir
            cache_file = os.path.join(
                self.cache_dir, "game_file", "map_object_data", file
            )
            if not os.path.exists(os.path.dirname(cache_file)):
                os.makedirs(os.path.dirname(cache_file))
            shutil.copy(base_game_file, cache_file)
