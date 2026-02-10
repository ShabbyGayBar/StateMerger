import os
import re
import yaml
import shutil
import pyradox
from vic3_state_merger.state_regions import StateRegion
from vic3_state_merger.buildings import Buildings
from vic3_state_merger.pops import Pops
from vic3_state_merger.states import States
from vic3_state_merger.trade import Trade

try:
    from importlib.resources import files, as_file
except ImportError:  # Python 3.8 / 3.7
    from importlib_resources import files, as_file  # pyright: ignore[reportMissingImports]

assets = files("vic3_state_merger") / "assets"

state_file_dir = {
    "map_data": r"map_data/state_regions",
    "state": r"common/history/states",
    "pops": r"common/history/pops",
    "buildings": r"common/history/buildings",
    "trade": r"common/history/trade",
}

replace_file_dir = [
    "common/ai_strategies",
    "common/buildings",
    "common/canals",
    "common/character_templates",
    "common/company_types",
    "common/country_creation",
    "common/country_definitions",
    "common/country_formation",
    "common/decisions",
    "common/dynamic_country_map_colors",
    "common/dynamic_country_names",
    "common/geographic_regions",
    "common/flag_definitions",
    "common/history/countries",
    "common/history/global",
    "common/history/diplomatic_plays",
    "common/history/military_formations",
    "common/journal_entries",
    "common/mobilization_options",
    "common/on_actions",
    "common/political_movements",
    "common/scripted_buttons",
    "common/scripted_effects",
    "common/scripted_triggers",
    "events",
    "events/agitators_events",
    "events/american_civil_war",
    "events/balkans_events",
    "events/brazil",
    "events/iberia_events",
    "events/india_events",
    "events/soi_events",
    "gfx/map/city_data/city_types",
]

remove_file_dir = ["common/strategic_regions"]

loc_file_dir = {
    "l_english": r"localization/english",
    "l_simp_chinese": r"localization/simp_chinese",
}

map_object_data_files = [
    "generated_map_object_locators_city.txt",
    "generated_map_object_locators_farm.txt",
    "generated_map_object_locators_mine.txt",
    "generated_map_object_locators_port.txt",
    "generated_map_object_locators_wood.txt",
]


def parse_merge(path, merge_levels:int=0):
    """Given a directory, return a Tree as if all .txt files in the directory were a single file"""

    result = pyradox.Tree()
    for filename in sorted(os.listdir(path)):
        fullpath = os.path.join(path, filename)
        if os.path.isfile(fullpath):
            tree = pyradox.parse_file(fullpath, game='HoI4', path_relative_to_game=False)
            result.merge(tree, merge_levels)
    return result


def clear_mod_dir(dir_dict:dict[str, str]):
    # Clear the output directory
    for dir in dir_dict.values():
        if not os.path.exists(dir):
            os.makedirs(dir)
        else:
            for file in os.listdir(dir):
                os.remove(os.path.join(dir, file))


def clean_v3_yml_numbered_keys(yml_path:str) -> str:
    with open(yml_path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Replace :<number> (optionally with spaces) before a quote or non-quote value
    cleaned = re.sub(r':\d+\s*"', ': "', raw)
    cleaned = re.sub(r':\d+\s+([^\n"]+)', r": \1", cleaned)
    return cleaned


class StateMerger:
    def __init__(self, game_root_dir:str, write_dir:str, merge_dict:dict, cache_dir:str="./data"):
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
        clear_mod_dir(self.mod_dir)

        # Parse State Regions data
        parser = parse_merge(
            self.base_game_dir["map_data"], merge_levels=1
        )
        self.map_data = StateRegion(parser)

        # Parse Buildings data
        parser = parse_merge(
            self.base_game_dir["buildings"], merge_levels=2
        )
        self.buildings = Buildings(parser)

        # Parse Pops data
        parser = parse_merge(self.base_game_dir["pops"], merge_levels=2)
        self.pops = Pops(parser)

        # Parse States data
        parser = parse_merge(
            self.base_game_dir["state"], merge_levels=2
        )
        self.states = States(parser)

        # Parse Trade data
        parser = parse_merge(
            self.base_game_dir["trade"], merge_levels=2
        )
        self.trade = Trade(parser)

    def merge_state_data(self, ignoreSmallStates:bool=False, smallStateLimit:int=4):
        # Write cleared base game data to mod directory
        for key, value in self.base_game_dir.items():
            for file in os.listdir(value):
                if file == "00_states_merging.txt":
                    continue
                with open(os.path.join(self.mod_dir[key], file), "w", encoding="utf-8-sig") as file:
                    file.write("")
        # Delete "/map_data/state_regions/99_sea.txt" in mod directory
        if os.path.exists(os.path.join(self.mod_dir["map_data"], "99_seas.txt")):
            os.remove(os.path.join(self.mod_dir["map_data"], "99_seas.txt"))

        # Merge map_data
        self.map_data.merge_states(
            self.merge_dict,
            ignoreSmallStates=ignoreSmallStates,
            smallStateLimit=smallStateLimit,
        )
        self.map_data.dump(os.path.join(self.mod_dir["map_data"], "00_states_merging.txt"))
        # Merge buildings
        self.buildings.merge_states(self.merge_dict)
        self.buildings.dump(os.path.join(self.mod_dir["buildings"], "00_states_merging.txt"))
        # Merge pops
        self.pops.merge_states(self.merge_dict)
        self.pops.dump(os.path.join(self.mod_dir["pops"], "00_states_merging.txt"))
        # Merge states
        self.states.merge_states(self.merge_dict)
        self.states.dump(os.path.join(self.mod_dir["state"], "00_states.txt"))
        # Merge trade
        self.trade.merge_states(self.merge_dict)
        self.trade.dump(os.path.join(self.mod_dir["trade"], "00_historical_trade.txt"))

        # Copy state_trait file to mod directory
        dir = os.path.join(self.write_dir, "common", "state_traits")
        file_str = (assets / "state_traits.txt").read_text(encoding="utf-8")
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(os.path.join(dir, "00_states_merging.txt")):
            os.remove(os.path.join(dir, "00_states_merging.txt"))
        with open(os.path.join(dir, "00_states_merging.txt"), "w", encoding="utf-8") as file:
            file.write(file_str)

    def merge_misc_data(self):
        for dir in replace_file_dir:
            base_game_dir = os.path.join(self.game_root_dir, dir)
            mod_dir = os.path.join(self.write_dir, dir)
            print("Scanning", base_game_dir)

            # Clear the output directory
            if not os.path.exists(mod_dir):
                os.makedirs(mod_dir)
            else:
                for file in os.listdir(mod_dir):
                    if os.path.isdir(os.path.join(mod_dir, file)):  # If is folder
                        continue
                    os.remove(os.path.join(mod_dir, file))

            for game_file in os.listdir(base_game_dir):
                if os.path.isdir(os.path.join(base_game_dir, game_file)):  # If is folder
                    continue

                # Read game file
                with open(os.path.join(base_game_dir, game_file), "r", encoding="utf-8") as file:
                    lines = file.readlines()
                text = "".join(lines)
                food_name_found = False

                for diner, food_list in self.merge_dict.items():
                    for food in food_list:
                        # Find all state names in the file
                        if re.search(r"\b" + re.escape(food) + r"\b", text):
                            food_name_found = True
                            break
                    if food_name_found:
                        break
                if not food_name_found:
                    continue

                print("Modifying", os.path.join(base_game_dir, game_file))
                # Replace all state names with their merged counterparts
                output_file = os.path.join(mod_dir, game_file)
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(output_file)):
                    os.makedirs(os.path.dirname(output_file))
                with open(output_file, "w", encoding="utf-8") as file:
                    for line in lines:
                        for diner, food_list in self.merge_dict.items():
                            for food in food_list:
                                # Replace "food" with "diner"
                                line = re.sub(
                                    r"\b" + re.escape(food) + r"\b", diner, line
                                )
                        file.write(line)

        for dir in remove_file_dir:
            base_game_dir = os.path.join(self.game_root_dir, dir)
            mod_dir = os.path.join(self.write_dir, dir)
            print("Scanning", base_game_dir)

            # Clear the output directory
            if not os.path.exists(mod_dir):
                os.makedirs(mod_dir)
            else:
                for file in os.listdir(mod_dir):
                    if os.path.isdir(os.path.join(mod_dir, file)):  # If is folder
                        continue
                    os.remove(os.path.join(mod_dir, file))

            for game_file in os.listdir(base_game_dir):
                if os.path.isdir(os.path.join(base_game_dir, game_file)):  # If is folder
                    continue

                # Read game file
                with open(os.path.join(base_game_dir, game_file), "r", encoding="utf-8") as file:
                    lines = file.readlines()

                food_name_found = False

                for diner, food_list in self.merge_dict.items():
                    for food in food_list:
                        # Find all state names in the file
                        if re.search(r"\b" + re.escape(food) + r"\b", "".join(lines)):
                            food_name_found = True
                            break
                    if food_name_found:
                        break
                if not food_name_found:
                    continue

                print("Modifying", os.path.join(base_game_dir, game_file))
                # Replace all state names with ""
                output_file = os.path.join(mod_dir, game_file)
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(output_file)):
                    os.makedirs(os.path.dirname(output_file))
                with open(output_file, "w", encoding="utf-8") as file:
                    for line in lines:
                        for diner, food_list in self.merge_dict.items():
                            for food in food_list:
                                # Replace "food" with ""
                                line = re.sub(r"\b" + re.escape(food) + r"\b", "", line)
                        file.write(line)

        # Copy USA flag adaptation file to mod directory
        dir = os.path.join(self.write_dir, "common", "flag_definitions")
        file_str = (assets / "01_flag_definitions_usa.txt").read_text(encoding="utf-8")
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(os.path.join(dir, "00_states_merging.txt")):
            os.remove(os.path.join(dir, "00_states_merging.txt"))
        with open(os.path.join(dir, "00_states_merging.txt"), "w", encoding="utf-8") as file:
            file.write(file_str)

        # Copy USA state counting file to mod directory
        dir = os.path.join(self.write_dir, "common", "script_values")
        file_str = (assets / "usa_state_counter.txt").read_text(encoding="utf-8")
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(os.path.join(dir, "00_states_merging.txt")):
            os.remove(os.path.join(dir, "00_states_merging.txt"))
        with open(os.path.join(dir, "00_states_merging.txt"), "w", encoding="utf-8") as file:
            file.write(file_str)

    def merge_loc_data(self):
        # Read localization yml files
        for lang, loc_dir in loc_file_dir.items():
            print(f"Reading localization files for {lang}...")
            hub_file = os.path.join(
                self.game_root_dir, loc_dir, f"hub_names_{lang}.yml"
            )
            miss_dict = {}
            with open(hub_file, "r", encoding="utf-8") as f:
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
        for file in map_object_data_files:
            base_game_file = os.path.join(self.game_root_dir, "gfx", "map", "map_object_data", file)
            # copy to cache dir
            cache_file = os.path.join(self.cache_dir, "game_file", "map_object_data", file)
            if not os.path.exists(os.path.dirname(cache_file)):
                os.makedirs(os.path.dirname(cache_file))
            shutil.copy(base_game_file, cache_file)
