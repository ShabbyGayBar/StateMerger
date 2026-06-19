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

state_file_dir = {
    "map_data": r"map_data/state_regions",
    "state": r"common/history/states",
    "pops": r"common/history/pops",
    "buildings": r"common/history/buildings",
    "trade": r"common/history/trade",
}

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

remove_keyword_file_dir = ["common/strategic_regions"]

loc_file_dir = {
    "l_english": r"localization/english",
    "l_simp_chinese": r"localization/simp_chinese",
}

map_object_data_files = {
    "city": "generated_map_object_locators_city.txt",
    "farm": "generated_map_object_locators_farm.txt",
    "mine": "generated_map_object_locators_mine.txt",
    "port": "generated_map_object_locators_port.txt",
    "wood": "generated_map_object_locators_wood.txt",
}

invalid_hub_names = ["NAME", "名称"]


def parse_merge(path, merge_levels: int = 0):
    """Given a directory, return a Tree as if all .txt files in the directory were a single file"""

    result = pyradox.Tree()
    for filename in sorted(os.listdir(path)):
        # Skip non-.txt files
        if not filename.endswith(".txt"):
            continue
        fullpath = os.path.join(path, filename)
        if os.path.isfile(fullpath):
            tree = pyradox.parse_file(
                fullpath, game="HoI4", path_relative_to_game=False
            )
            result.merge(tree, merge_levels)
    return result


def clean_v3_yml_numbered_keys(yml_path: str) -> str:
    with open(yml_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    # Replace :<number> (optionally with spaces) before a quote or non-quote value
    cleaned = re.sub(r':\d+\s*"', ': "', raw)
    cleaned = re.sub(r':\d+\s+([^\n"]+)', r": \1", cleaned)
    return cleaned


def _prefix_replace(text: str) -> str:
    """Prefix 'REPLACE:' on first-level assignment lines (no extra newlines).

    Leaves comments, indented lines, blank lines, and already-prefixed lines alone.
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
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        return
    for file in os.listdir(dir_path):
        if os.path.isdir(os.path.join(dir_path, file)):
            continue
        os.remove(os.path.join(dir_path, file))


def _build_keyword_pattern(merge_dict: dict):
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
        r"(?<![0-9A-Za-z])("
        + "|".join(map(re.escape, keys))
        + r")(?![0-9A-Za-z])"
    )
    return lookup, pattern


def _keyword_replace(match, lookup, text):
    key = match.group(1)
    start = match.start(1)
    end = match.end(1)
    if end < len(text) and text[end] == "_" and end + 1 < len(text) and text[end + 1].isupper():
        return key
    if start >= 2 and text[start - 1] == "_" and text[start - 2].isupper():
        prefix = text[:start]
        if re.search(r"STATE_[A-Z0-9_]*_$", prefix):
            return key
    return lookup[key]


def _keyword_remove(match, lookup, text):
    key = match.group(1)
    start = match.start(1)
    end = match.end(1)
    if end < len(text) and text[end] == "_" and end + 1 < len(text) and text[end + 1].isupper():
        return key
    if start >= 2 and text[start - 1] == "_" and text[start - 2].isupper():
        prefix = text[:start]
        if re.search(r"STATE_[A-Z0-9_]*_$", prefix):
            return key
    return ""


def _iter_txt_files(base_game_dir: str):
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

        # Parse State Regions data
        parser = parse_merge(self.base_game_dir["map_data"], merge_levels=1)
        self.map_data = StateRegion(parser)

        # Parse Buildings data
        parser = parse_merge(self.base_game_dir["buildings"], merge_levels=2)
        self.buildings = Buildings(parser)

        # Parse Pops data
        parser = parse_merge(self.base_game_dir["pops"], merge_levels=2)
        self.pops = Pops(parser)

        # Parse States data
        parser = parse_merge(self.base_game_dir["state"], merge_levels=2)
        self.states = States(parser)

        # Parse Trade data
        parser = parse_merge(self.base_game_dir["trade"], merge_levels=2)
        self.trade = Trade(parser)

    def merge_state_data(
        self, ignoreSmallStates: bool = False, smallStateLimit: int = 4
    ):
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
        # Write cleared base game data to mod directory
        for key, value in self.base_game_dir.items():
            for file in os.listdir(value):
                if file == "state_merging.txt":
                    continue
                with open(
                    os.path.join(self.mod_dir[key], file), "w", encoding="utf-8-sig"
                ) as file:
                    file.write("")
        # Delete "/map_data/state_regions/99_sea.txt" in mod directory
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

        # Copy state_trait file to mod directory
        dir = os.path.join(self.write_dir, "common", "state_traits")
        file_str = vic3_state_merger.assets.state_traits.str
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
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
        output_dir = os.path.join(self.write_dir, "gfx", "map", "map_object_data")
        _clear_output_dir(output_dir)

        for file in map_object_data_files.values():
            base_game_file = os.path.join(
                self.game_root_dir, "gfx", "map", "map_object_data", file
            )
            if not os.path.exists(base_game_file):
                continue

            parser = pyradox.parse_file(
                base_game_file, game="HoI4", path_relative_to_game=False
            )
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
                    map_object_data.retarget_instance_id(source_id, target_id)

                removal_ids = {state_id for state_id in source_ids if state_id != target_id}
                if source_id != target_id:
                    removal_ids.discard(source_id)
                if removal_ids:
                    map_object_data.remove_instances_by_id(removal_ids)

            _write_text_file(os.path.join(output_dir, file), str(map_object_data))

    def merge_misc_data(self):
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
                lambda text, lookup, pattern: pattern.sub(lambda m: _keyword_replace(m, lookup, text), text),
            )

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
                lambda text, lookup, pattern: pattern.sub(lambda m: _keyword_replace(m, lookup, text), text),
                aggregate=True,
            )

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
                lambda text, lookup, pattern: pattern.sub(lambda m: _keyword_remove(m, lookup, text), text),
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
            os.path.join(dir, "state_merging_flag_definition_usa.txt"), "w", encoding="utf-8-sig"
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
            os.path.join(dir, "state_merging_usa_state_counter.txt"), "w", encoding="utf-8-sig"
        ) as file:
            file.write(file_str)

    def merge_loc_data(self):
        # Read localization yml files
        for lang, loc_dir in loc_file_dir.items():
            print(f"Reading localization files for {lang}...")
            hub_file = os.path.join(
                self.game_root_dir, loc_dir, f"hub_names_{lang}.yml"
            )
            miss_dict = {}
            with open(hub_file, "r", encoding="utf-8-sig") as f:
                cleaned_yml = clean_v3_yml_numbered_keys(hub_file)
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

                    # Check if city, wood, mine, farm, port attribute of diner are in the localization data
                    for attr in ["city", "wood", "mine", "farm", "port"]:
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
                    # Remove all '\'' in write_file
                    content = content.replace("'", "")
                    f.write(content)

    def copy_state_data(self):
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
