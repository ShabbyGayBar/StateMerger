from paradox_file_parser import ParadoxFileParser
import os
import re
import json
import yaml
import shutil

state_file_dir = {
    "map_data": r"map_data/state_regions/",
    "state": r"common/history/states/",
    "pops": r"common/history/pops/",
    "buildings": r"common/history/buildings/",
    "trade": r"common/history/trade/"
}

replace_file_dir = [
    "common/ai_strategies/",
    "common/buildings/",
    "common/canals/",
    "common/character_templates/",
    "common/company_types/",
    "common/country_creation/",
    "common/country_definitions/",
    "common/country_formation/",
    "common/decisions/",
    "common/dynamic_country_names/",
    "common/flag_definitions/",
    "common/history/countries/",
    "common/history/global/",
    "common/history/diplomatic_plays/",
    "common/history/military_formations/",
    "common/journal_entries/",
    "common/on_actions/",
    "common/scripted_buttons/",
    "common/scripted_effects/",
    "common/scripted_triggers/",
    "events/",
    "events/agitators_events/",
    "events/american_civil_war/",
    "events/brazil/",
    "events/india_events/",
    "events/soi_events/"
]

remove_file_dir = [
    "common/strategic_regions/"
]

loc_file_dir = {
    "l_english": r"localization/english/",
    "l_simp_chinese": r"localization/simp_chinese/"
}

seq_str = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]

def clear_mod_dir(dir_dict):
    # Clear the output directory
    for dir in dir_dict.values():
        if not os.path.exists(dir):
            os.makedirs(dir)
        else:
            for file in os.listdir(dir):
                os.remove(os.path.join(dir, file))

def clean_v3_yml_numbered_keys(yml_path):
    with open(yml_path, 'r', encoding='utf-8') as f:
        raw = f.read()
    # Replace :<number> (optionally with spaces) before a quote or non-quote value
    cleaned = re.sub(r':\d+\s*"', ': "', raw)
    cleaned = re.sub(r':\d+\s+([^\n"]+)', r': \1', cleaned)
    return cleaned

class ModState:
    def __init__(self, base_game_dir, mod_dir, diff=False):
        self.base_parsers = {}
        self.mod_parsers = {}
        self.load_directory_files(base_game_dir, mod_dir, diff)

    def load_directory_files(self, base_game_dir, mod_dir, diff=False):
        for entity_type, dir_path in base_game_dir.items():
            self.base_parsers[entity_type] = ParadoxFileParser()
            self.mod_parsers[entity_type] = ParadoxFileParser()
            self.load_files_from_directory(entity_type, dir_path, base_game=True)

            if diff:
                self.mod_parsers[entity_type].set_data_from_changes_json(
                    self.base_parsers[entity_type],
                    mod_dir + os.sep + entity_type + ".json",
                )
            else:
                if entity_type in mod_dir:
                    self.load_files_from_directory(
                        entity_type, mod_dir[entity_type], base_game=False
                    )

    def load_files_from_directory(self, entity_type, dir_path, base_game=True):
        for file_name in os.listdir(dir_path):
            if file_name.startswith("_"):
                continue
            file_path = os.path.join(dir_path, file_name)
            if os.path.isfile(file_path):
                print("reading file:", file_path)
                if base_game:
                    self.base_parsers[entity_type].parse_file(file_path)
                    self.mod_parsers[entity_type].parse_file(file_path)
                else:
                    mod_data = self.parse_mod_file(file_path)
                    self.mod_parsers[entity_type].merge_data(mod_data)

    def parse_mod_file(self, file_path):
        parser = ParadoxFileParser()
        parser.parse_file(file_path)
        return parser.data

    def get_data(self, entity_type):
        return (
            self.mod_parsers[entity_type].data
            if entity_type in self.mod_parsers
            else None
        )

    def get_string_form(self, entity_type):
        return (
            str(self.mod_parsers[entity_type])
            if entity_type in self.mod_parsers
            else None
        )

    def update_and_write_file(self, entity_type, file_path):
        if entity_type in self.mod_parsers:
            self.mod_parsers[entity_type].write_file(
                file_path, self.base_parsers[entity_type]
            )

    def save_changes_to_json(self, file_path, entity_type=None):
        if entity_type is None:
            for entity_type in self.mod_parsers:
                self.mod_parsers[entity_type].save_changes_to_json(
                    self.base_parsers[entity_type],
                    file_path + os.sep + entity_type + ".json",
                )
        else:
            if entity_type in self.mod_parsers:
                self.mod_parsers[entity_type].save_changes_to_json(
                    self.base_parsers[entity_type], file_path
                )
            else:
                raise Exception(f"entity_type {entity_type} not found")

class StateRegion:
    '''Class for state objects in 'StateMergingToolkit/map_data'
    name: string, state name
    id: int, state id
    subsistence_building: string, what kind of subsistence building the state has
    provinces: list of string, provinces in the state
    impassable: list of string, impassable provinces in the state
    traits: list of string, traits of the state
    city: string, province id of the state capital
    port: string, province id of the state port
    farm: string, province id of the state farm
    mine: string, province id of the state mine
    wood: string, province id of the state wood
    arable_land: int, amount of arable land in the state
    arable_resources: list of string, what kind of available agriculture buildings the state has
    capped_resources: dict, capped resources in the state
    naval_exit_id: int, corresponding sea node id for the state
    '''
    def __init__(self, name, dict):
        '''Initialize the state object with a dictionary
        '''
        self.name = ''
        self.id = 0
        self.subsistence_building = ''
        self.provinces = []
        self.impassable = []
        self.prime_land = []
        self.traits = []
        self.city = ''
        self.port = ''
        self.farm = ''
        self.mine = ''
        self.wood = ''
        self.arable_land = 0
        self.arable_resources = []
        self.capped_resources = {}
        self.gold = [0,0] # gold[0]: undiscovered, gold[1]: discovered
        self.rubber = [0,0] # rubber[0]: undiscovered, rubber[1]: discovered
        self.oil = 0
        self.naval_exit_id = -1

        self.name = name
        dict_data = dict[name]
        self.id = int(dict_data['id'])
        if "subsistence_building" not in dict_data.keys(): # Check if is sea node
            self.subsistence_building = ''
            self.provinces = dict_data['provinces']
            return
        self.subsistence_building = dict_data['subsistence_building']
        self.provinces = dict_data['provinces']
        if 'impassable' in dict_data.keys():
            self.impassable = dict_data['impassable']
        else:
            self.impassable = []
        if 'prime_land' in dict_data.keys():
            self.prime_land = dict_data['prime_land']
        else:
            self.prime_land = []
        if 'traits' in dict_data.keys():
            self.traits = dict_data['traits']
        else:
            self.traits = []
        if 'city' in dict_data.keys():
            self.city = dict_data['city']
        else:
            self.city = ''
        if 'port' in dict_data.keys():
            self.port = dict_data['port']
        else:
            self.port = ''
        if 'farm' in dict_data.keys():
            self.farm = dict_data['farm']
        else:
            self.farm = ''
        if 'mine' in dict_data.keys():
            self.mine = dict_data['mine']
        else:
            self.mine = ''
        if 'wood' in dict_data.keys():
            self.wood = dict_data['wood']
        else:
            self.wood = ''
        self.arable_land = int(dict_data['arable_land'])
        self.arable_resources = dict_data['arable_resources']
        self.capped_resources = {}
        if 'capped_resources' in dict_data.keys():
            for resource, amount in dict_data['capped_resources'].items():
                self.capped_resources[resource] = int(amount)
        if 'resource' in dict_data.keys():
            for resource in dict_data['resource']:
                if resource['type'] == '\"bg_gold_fields\"':
                    self.gold[0] = int(resource['undiscovered_amount'])
                    if 'discovered_amount' in resource.keys():
                        self.gold[1] = int(resource['discovered_amount'])
                elif resource['type'] == '\"bg_rubber\"':
                    if 'undiscovered_amount' in resource.keys():
                        self.rubber[0] = int(resource['undiscovered_amount'])
                    if 'discovered_amount' in resource.keys():
                        self.rubber[1] = int(resource['discovered_amount'])
                elif resource['type'] == '\"bg_oil_extraction\"':
                    self.oil = int(resource['undiscovered_amount'])
                else:
                    print(f'Unknown resource type: {resource["type"]}')
        if 'naval_exit_id' in dict_data.keys():
            self.naval_exit_id = dict_data['naval_exit_id']
        else:
            self.naval_exit_id = -1

    def merge_states_cnt(self):
        '''Determine the number of states merged in the state
        '''
        if self.is_sea_node():
            return 0
        for i in range(2, 9):
            if f'"state_trait_{seq_str[i]}_states_integration"' in self.traits:
                return i
        return 1
    
    def merge_coast_cnt(self):
        '''Determine the number of coast states merged in the state
        '''
        if self.is_sea_node():
            return 0
        if self.naval_exit_id == -1:
            return 0
        for i in range(2, 7):
            if f'"state_trait_{seq_str[i]}_coast_integration"' in self.traits:
                return i
        return 1
    
    def is_sea_node(self):
        '''Determine if the state is a sea node
        '''
        if self.subsistence_building == '':
            return True
        return False

    def province_cnt(self):
        '''Return the number of provinces in the state
        '''
        return len(self.provinces)

    def is_small_state(self, limit=4):
        '''Determine if the state is a small state
        '''
        if self.is_sea_node():
            return False
        if self.province_cnt() < limit:
            return True
        return False

    def merge(self, other, ignoreSmallStates=False, smallStateLimit=4):
        '''Merge two state objects.
        '''
        if self.is_sea_node() or other.is_sea_node():
            print(f'Error: Cannot merge sea node with other state')
            return
        # provinces: list append
        self.provinces += other.provinces
        # impassable: list append
        self.impassable += other.impassable
        # prime_land: list append
        self.prime_land += other.prime_land
        # traits: list append, remove "state_trait_two_states_integration", "state_trait_three_states_integration", "state_trait_four_states_integration", etc., and add the corresponding trait according to merge_states_cnt(convert to string)
        thisMergeStatesCnt = self.merge_states_cnt()
        otherMergeStatesCnt = other.merge_states_cnt()
        thisCoastCnt = self.merge_coast_cnt()
        otherCoastCnt = other.merge_coast_cnt()
        if thisMergeStatesCnt > 1:
            self.traits.remove(f'"state_trait_{seq_str[thisMergeStatesCnt]}_states_integration"')
        if thisCoastCnt > 1:
            self.traits.remove(f'"state_trait_{seq_str[thisCoastCnt]}_coast_integration"')
        for trait in other.traits:
            if trait != f'"state_trait_{seq_str[otherMergeStatesCnt]}_states_integration"' and trait != f'"state_trait_{seq_str[otherCoastCnt]}_coast_integration"' and trait not in self.traits:
                self.traits.append(trait)
        totalMergeStatesCnt = thisMergeStatesCnt + otherMergeStatesCnt
        totalCoastCnt = thisCoastCnt + otherCoastCnt
        if (ignoreSmallStates):
            if self.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
                totalCoastCnt -= 1
            if other.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
                totalCoastCnt -= 1
        if (totalMergeStatesCnt > 1) and (totalMergeStatesCnt < 8):
            self.traits.append(f'"state_trait_{seq_str[totalMergeStatesCnt]}_states_integration"')
        elif (totalMergeStatesCnt >= 8):
            self.traits.append('"state_trait_eight_states_integration"')
        if (totalCoastCnt > 1) and (totalCoastCnt < 6):
            self.traits.append(f'"state_trait_{seq_str[totalCoastCnt]}_coast_integration"')
        elif (totalCoastCnt >= 6):
            self.traits.append('"state_trait_six_coast_integration"')
        # arable_land: int sum
        self.arable_land += other.arable_land
        # arable_resources: list append
        for resource in other.arable_resources:
            if resource not in self.arable_resources:
                self.arable_resources.append(resource)
        # capped_resources: dict add each key-value pair
        for resource, amount in other.capped_resources.items():
            if resource in self.capped_resources.keys():
                self.capped_resources[resource] += int(amount)
            else:
                self.capped_resources[resource] = int(amount)
        # gold, rubber, oil: int sum
        self.gold[0] += other.gold[0]
        self.gold[1] += other.gold[1]
        self.rubber[0] += other.rubber[0]
        self.rubber[1] += other.rubber[1]
        self.oil += other.oil
        # city, port, farm, mine, wood, naval_exit_id: keep the value of self except they are '' or -1, in which case update them with the value of other
        if self.port == '':
            self.port = other.port
        if self.mine == '':
            self.mine = other.mine
        if self.wood == '':
            self.wood = other.wood
        if self.naval_exit_id == -1:
            self.naval_exit_id = other.naval_exit_id
        # clear provinces, impassable, traits, arable_land, arable_resources, capped_resources of other
        other.provinces = []
        other.impassable = []
        other.prime_land = []
        other.traits = []
        other.arable_land = 0
        other.arable_resources = []
        other.capped_resources = {}
        other.gold = [0, 0]
        other.rubber = [0, 0]
        other.oil = 0
 
    def __str__(self):
        '''Export the state object to a string
        '''
        state_str = f'{self.name} = {{\n'
        state_str += f'    id = {self.id}\n'
        if self.is_sea_node():
            state_str += f'    provinces = {{ '
            for province in self.provinces:
                state_str += f'{province} '
            state_str += f'}}\n'
            state_str += f'}}\n\n'
            return state_str
        state_str += f'    subsistence_building = {self.subsistence_building}\n'
        state_str += f'    provinces = {{ '
        for province in self.provinces:
            state_str += f'{province} '
        state_str += f'}}\n'
        if self.impassable != []:
            state_str += f'    impassable = {{ '
            for province in self.impassable:
                state_str += f'{province} '
            state_str += f'}}\n'
        if self.prime_land != []:
            state_str += f'    prime_land = {{ '
            for province in self.prime_land:
                state_str += f'{province} '
            state_str += f'}}\n'
        if self.traits != []:
            state_str += f'    traits = {{ '
            for trait in self.traits:
                state_str += f'{trait} '
            state_str += f'}}\n'
        if self.city != '':
            state_str += f'    city = {self.city}\n'
        if self.port != '':
            state_str += f'    port = {self.port}\n'
        if self.farm != '':
            state_str += f'    farm = {self.farm}\n'
        if self.mine != '':
            state_str += f'    mine = {self.mine}\n'
        if self.wood != '':
            state_str += f'    wood = {self.wood}\n'
        state_str += f'    arable_land = {self.arable_land}\n'
        state_str += f'    arable_resources = {{ '
        for resource in self.arable_resources:
            state_str += f'{resource} '
        state_str += f'}}\n'
        if self.capped_resources:
            state_str += f'    capped_resources = {{\n'
            for resource, amount in self.capped_resources.items():
                state_str += f'        {resource} = {amount}\n'
            state_str += f'    }}\n'
        if self.gold != [0, 0]:
            state_str += f'    resource = {{\n'
            state_str += f'        type = "bg_gold_fields"\n'
            state_str += f'        depleted_type = "bg_gold_mining"\n'
            if self.gold[0] != 0:
                state_str += f'        undiscovered_amount = {self.gold[0]}\n'
            if self.gold[1] != 0:
                state_str += f'        discovered_amount = {self.gold[1]}\n'
            state_str += f'    }}\n'
        if self.rubber != [0, 0]:
            state_str += f'    resource = {{\n'
            state_str += f'        type = "bg_rubber"\n'
            if self.rubber[0] != 0:
                state_str += f'        undiscovered_amount = {self.rubber[0]}\n'
            if self.rubber[1] != 0:
                state_str += f'        discovered_amount = {self.rubber[1]}\n'
            state_str += f'    }}\n'
        if self.oil != 0:
            state_str += f'    resource = {{\n'
            state_str += f'        type = "bg_oil_extraction"\n'
            state_str += f'        undiscovered_amount = {self.oil}\n'
            state_str += f'    }}\n'
        if self.naval_exit_id != -1:
            state_str += f'    naval_exit_id = {self.naval_exit_id}\n'
        state_str += f'}}\n\n'

        return state_str

class MapData:
    def __init__(self, states_dict):
        self.data = {}
        for state_id in states_dict.keys():
            print("Reading map_data: "+state_id)
            if 'impassable' in states_dict[state_id].keys():
                if isinstance(states_dict[state_id]['impassable'], str):
                    states_dict[state_id]['impassable'] = [states_dict[state_id]['impassable']]
            if 'prime_land' in states_dict[state_id].keys():
                if isinstance(states_dict[state_id]['prime_land'], str):
                    states_dict[state_id]['prime_land'] = [states_dict[state_id]['prime_land']]
            if 'traits' in states_dict[state_id].keys():
                if isinstance(states_dict[state_id]['traits'], str):
                    states_dict[state_id]['traits'] = [states_dict[state_id]['traits']]
            if 'arable_resources' in states_dict[state_id].keys():
                if isinstance(states_dict[state_id]['arable_resources'], str):
                    states_dict[state_id]['arable_resources'] = [states_dict[state_id]['arable_resources']]
            if 'resource' in states_dict[state_id].keys():
                if isinstance(states_dict[state_id]['resource'], dict):
                    states_dict[state_id]['resource'] = [states_dict[state_id]['resource']]
            self.data[state_id] = StateRegion(state_id, states_dict)

    def merge(self, merge_dict, ignoreSmallStates=False, smallStateLimit=4):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if food in self.data.keys():
                    print(f'Merging {food} map_data into {diner}')
                    if self.data[food].is_sea_node():
                        print(f'{food} is a sea node, skipping...')
                        continue
                    self.data[diner].merge(self.data[food], ignoreSmallStates=ignoreSmallStates, smallStateLimit=smallStateLimit)
                    self.data.pop(food)

    def dump(self, dir, include_sea_nodes=False):
        with open(dir, 'w', encoding='utf-8-sig') as file:
            for state_id in self.data.keys():
                print("Exporting map_data: "+state_id)
                if not include_sea_nodes and self.data[state_id].is_sea_node():
                    print(f'{state_id} is a sea node, skipping...')
                    continue
                file.write(str(self.data[state_id]))

class Building:
    def __init__(self, dict):
        '''Initialize the building object with a dictionary'''
        if "building" in dict.keys():
            self.building = dict["building"]
        else:
            self.building = None
        self.building_ownership = []
        self.country_ownership = []
        self.company_ownership = []
        self.reserves = 0
        self.activate_production_methods = []
        self.isMonument = ("level" in dict.keys())
        if self.isMonument: return
        if "add_ownership" in dict.keys():
            if "building" in dict["add_ownership"].keys():
                if not isinstance(dict["add_ownership"]["building"], list):
                    dict["add_ownership"]["building"] = [dict["add_ownership"]["building"]]
                self.building_ownership = dict["add_ownership"]["building"]
            if "country" in dict["add_ownership"].keys():
                if not isinstance(dict["add_ownership"]["country"], list):
                    dict["add_ownership"]["country"] = [dict["add_ownership"]["country"]]
                self.country_ownership = dict["add_ownership"]["country"]
            if "company" in dict["add_ownership"].keys():
                if not isinstance(dict["add_ownership"]["company"], list):
                    dict["add_ownership"]["company"] = [dict["add_ownership"]["company"]]
                self.company_ownership = dict["add_ownership"]["company"]
        if "reserves" in dict.keys():
            self.reserves = int(dict["reserves"])
        if "activate_production_methods" in dict.keys():
            self.activate_production_methods = dict["activate_production_methods"]
        self.refresh()

    def is_empty(self):
        '''Check if the building object is empty'''
        if self.building is None:
            return True
        if self.isMonument:
            return False
        if (not self.building_ownership and not self.country_ownership and not self.company_ownership):
            return True
        return False
    
    def refresh(self):
        '''Sort ownerships and merge duplicate ownerships'''
        if self.is_empty():
            self.building = None
            self.building_ownership = []
            self.country_ownership = []
            self.company_ownership = []
            return
        sorted_ownership = []
        for other_ownership in self.building_ownership:
            found = False
            for this_ownership in sorted_ownership:
                if (this_ownership["type"] == other_ownership["type"] and
                    this_ownership["country"] == other_ownership["country"] and
                    this_ownership["region"] == other_ownership["region"]):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(other_ownership["levels"])
                    break
            if not found:
                sorted_ownership.append(other_ownership)
        self.building_ownership = sorted_ownership
        if not isinstance(self.activate_production_methods, list):
            self.activate_production_methods = [self.activate_production_methods]

    def level_cnt(self):
        if self.isMonument: return 1
        levels = 0
        for ownership in (self.building_ownership + self.country_ownership + self.company_ownership):
            levels += int(ownership["levels"])
        return levels
    
    def __iadd__(self, other):
        '''Add two building objects together'''
        if self.building != other.building:
            raise ValueError("Cannot add buildings with different types")
        for ownership in other.building_ownership:
            found = False
            for this_ownership in self.building_ownership:
                if (this_ownership["type"] == ownership["type"] and
                    this_ownership["country"] == ownership["country"] and
                    this_ownership["region"] == ownership["region"]):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(ownership["levels"])
                    break
            if not found:
                self.building_ownership.append(ownership)
        for ownership in other.country_ownership:
            found = False
            for this_ownership in self.country_ownership:
                if this_ownership["country"] == ownership["country"]:
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(ownership["levels"])
                    break
            if not found:
                self.country_ownership.append(ownership)
        for ownership in other.company_ownership:
            found = False
            for this_ownership in self.company_ownership:
                if (this_ownership["type"] == ownership["type"] and
                    this_ownership["country"] == ownership["country"]):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(ownership["levels"])
                    break
            if not found:
                self.company_ownership.append(ownership)
        return self
    
    def __str__(self):
        building_str = f"            create_building = {{\n"
        if self.is_empty():
            building_str += "            }\n"
            return building_str
        building_str += f"                building = {self.building}\n"
        if self.isMonument:
            building_str += f"                level = 1\n"
            building_str += "            }\n"
            return building_str
        building_str += f"                add_ownership = {{\n"
        for ownership in self.building_ownership:
            building_str += f"                    building = {{\n"
            building_str += f"                        type = {ownership['type']}\n"
            building_str += f"                        country = {ownership['country']}\n"
            building_str += f"                        levels = {ownership['levels']}\n"
            building_str += f"                        region = {ownership['region']}\n"
            building_str += f"                    }}\n"
        for ownership in self.country_ownership:
            building_str += f"                    country = {{\n"
            building_str += f"                        country = {ownership['country']}\n"
            building_str += f"                        levels = {ownership['levels']}\n"
            building_str += f"                    }}\n"
        for ownership in self.company_ownership:
            building_str += f"                    company = {{\n"
            building_str += f"                        type = {ownership['type']}\n"
            building_str += f"                        country = {ownership['country']}\n"
            building_str += f"                        levels = {ownership['levels']}\n"
            building_str += f"                    }}\n"
        building_str += f"                }}\n"
        building_str += f"                reserves = {self.reserves}\n"
        building_str += f"                activate_production_methods = {{\n"
        for method in self.activate_production_methods:
            building_str += f"                    {method}\n"
        building_str += f"                }}\n"
        building_str += f"            }}\n"
        return building_str

class Buildings:
    def __init__(self, buildings_dict):
        self.data = {}
        for state_id in buildings_dict["BUILDINGS"].keys():
            if state_id == "if": # dlc buildings
                continue
            print("Reading buildings: "+state_id)
            self.data[state_id] = {}
            for tag in buildings_dict["BUILDINGS"][state_id].keys():
                self.data[state_id][tag] = []
                if (not isinstance(buildings_dict["BUILDINGS"][state_id][tag], dict)) or ("create_building" not in buildings_dict["BUILDINGS"][state_id][tag].keys()):
                    continue
                if not isinstance(buildings_dict["BUILDINGS"][state_id][tag]["create_building"], list):
                    buildings_dict["BUILDINGS"][state_id][tag]["create_building"] = [buildings_dict["BUILDINGS"][state_id][tag]["create_building"]]
                for building in buildings_dict["BUILDINGS"][state_id][tag]["create_building"]:
                    self.data[state_id][tag].append(Building(building))
        self.format()

    def format(self):
        for state_id in self.data.keys(): # Restore the original structure of certain building keys
            if state_id == "if":
                continue
            for tag in self.data[state_id].keys():
                for i in range(len(self.data[state_id][tag]), 0, -1):
                    if self.data[state_id][tag][i-1].is_empty():
                        self.data[state_id][tag].pop(i-1)

    def merge(self, merge_dict):
        # Merge building ownerships
        for state_id in self.data.keys():
            if state_id == "if": # dlc buildings
                continue
            for tag in self.data[state_id].keys():
                if not isinstance(self.data[state_id][tag], list):
                    continue
                for building in self.data[state_id][tag]:
                    if building.is_empty() or building.isMonument:
                        continue
                    for ownership in building.building_ownership:
                        region = ownership["region"].replace('\"', '') # Remove '\"' from ownership["region"]
                        for diner, food_list in merge_dict.items():
                            if region in food_list:
                                ownership["region"] = '\"'+diner+'\"'
                                building.refresh()
                                break
        # Merge building
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:"+food) in self.data.keys():
                    print(f'Merging {food} building data into {diner}')
                    # self.merge_by_id("s:"+diner, "s:"+food)
                    for tag in self.data["s:"+food].keys():
                        if tag not in self.data["s:"+diner].keys():
                            self.data["s:"+diner][tag] = self.data["s:"+food][tag]
                            continue
                        for other_building in self.data["s:"+food][tag]:
                            if other_building.is_empty():
                                continue
                            found = False
                            for this_building in self.data["s:"+diner][tag]:
                                if this_building.building == other_building.building:
                                    found = True
                                    this_building += other_building
                                    break
                            if not found:
                                self.data["s:"+diner][tag].append(other_building)
                    # Remove the food from data
                    self.data.pop("s:"+food)
        self.format()

    def get_str(self, state_id):
        if state_id == "if":
            return ""
        building_str = f'    {state_id} = {{\n'
        for tag in self.data[state_id].keys():
            building_str += f'        {tag} = {{\n'
            for building in self.data[state_id][tag]:
                building_str += str(building)
            building_str += f'        }}\n'
        building_str += f'    }}\n'

        return building_str

    def dump(self, dir):
        with open(dir, 'w', encoding='utf-8-sig') as file:
            file.write('BUILDINGS = {\n')
            for state_id in self.data.keys():
                print("Exporting building data: "+state_id)
                file.write(self.get_str(state_id))
            file.write('}\n')

class Pops:
    def __init__(self, pops_dict):
        self.data = pops_dict["POPS"]
        self.format()

    def format(self):
        for state_id in self.data.keys(): # Restore the original structure of certain pop keys
            print(f'Formatting pop data: {state_id}')
            for tag in self.data[state_id].keys():
                if not isinstance(self.data[state_id][tag], dict):
                    self.data[state_id][tag] = {"create_pop": []}
                    continue
                if isinstance(self.data[state_id][tag]["create_pop"], tuple):
                    self.data[state_id][tag]["create_pop"] = list(self.data[state_id][tag]["create_pop"])
                elif not isinstance(self.data[state_id][tag]["create_pop"], list):
                    self.data[state_id][tag]["create_pop"] = [self.data[state_id][tag]["create_pop"]]

    def merge_by_id(self, this, other): # this, other are "state_id" strings
        for tag in self.data[other].keys():
            if tag in self.data[this].keys():
                for other_pop in self.data[other][tag]["create_pop"]:
                    found = False
                    hasAttributeType = "pop_type" in other_pop
                    hasAttributeReligion = "religion" in other_pop
                    for this_pop in self.data[this][tag]["create_pop"]:
                        if other_pop["culture"] != this_pop["culture"]:
                            continue
                        if hasAttributeType and "pop_type" in this_pop:
                            if other_pop["pop_type"] == this_pop["pop_type"]:
                                if hasAttributeReligion and "religion" in this_pop:
                                    if other_pop["religion"] == this_pop["religion"]:
                                        this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                                        found = True
                                        break
                                elif not hasAttributeReligion and "religion" not in this_pop:
                                    this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                                    found = True
                                    break
                            continue
                        elif not hasAttributeType and "pop_type" not in this_pop:
                            if hasAttributeReligion and "religion" in this_pop:
                                if other_pop["religion"] == this_pop["religion"]:
                                    this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                                    found = True
                                    break
                            elif not hasAttributeReligion and "religion" not in this_pop:
                                this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                                found = True
                                break
                    if not found:
                        self.data[this][tag]["create_pop"].append(other_pop)
            else:
                self.data[this][tag] = self.data[other][tag]

    def get_str(self, state_id):
        state_str = f'    {state_id} = {{\n'
        for tag in self.data[state_id].keys():
            state_str += f'        {tag} = {{\n'
            for pop in self.data[state_id][tag]["create_pop"]:
                state_str += f'            create_pop = {{\n'
                for key, value in pop.items():
                    state_str += f'                {key} = {value}\n'
                state_str += f'            }}\n'
            state_str += f'        }}\n'
        state_str += f'    }}\n'

        return state_str

    def merge(self, merge_dict):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:"+food) in self.data.keys():
                    print(f'Merging {food} pop data into {diner}')
                    self.merge_by_id(("s:"+diner), ("s:"+food))
                    self.data.pop("s:"+food)

    def dump(self, dir):
        with open(dir, 'w', encoding='utf-8-sig') as file:
            file.write('POPS = {\n')
            for state_id in self.data.keys():
                print("Exporting pop data: "+state_id)
                file.write(self.get_str(state_id))
            file.write('}\n')

class States:
    def __init__(self, states_dict):
        self.data = states_dict["STATES"]
        self.format()

    def format(self):
        for state_id in self.data.keys():
            print(f'Formatting state data: {state_id}')
            if not isinstance(self.data[state_id], dict):
                self.data[state_id] = {"create_state": []}
                continue
            if isinstance(self.data[state_id]["create_state"], tuple):
                self.data[state_id]["create_state"] = list(self.data[state_id]["create_state"])
            elif not isinstance(self.data[state_id]["create_state"], list):
                self.data[state_id]["create_state"] = [self.data[state_id]["create_state"]]
            for state in self.data[state_id]["create_state"]:
                if isinstance(state["owned_provinces"], tuple):
                    state["owned_provinces"] = list(state["owned_provinces"])
                elif not isinstance(state["owned_provinces"], list):
                    state["owned_provinces"] = [state["owned_provinces"]]
                if "state_type" in state.keys():
                    if isinstance(state["state_type"], tuple):
                        state["state_type"] = list(state["state_type"])
                    elif not isinstance(state["state_type"], list):
                        state["state_type"] = [state["state_type"]]
            if "add_homeland" in self.data[state_id].keys():
                if isinstance(self.data[state_id]["add_homeland"], tuple):
                    self.data[state_id]["add_homeland"] = list(self.data[state_id]["add_homeland"])
                elif not isinstance(self.data[state_id]["add_homeland"], list):
                    self.data[state_id]["add_homeland"] = [self.data[state_id]["add_homeland"]]
            if "add_claim" in self.data[state_id].keys():
                if isinstance(self.data[state_id]["add_claim"], tuple):
                    self.data[state_id]["add_claim"] = list(self.data[state_id]["add_claim"])
                elif not isinstance(self.data[state_id]["add_claim"], list):
                    self.data[state_id]["add_claim"] = [self.data[state_id]["add_claim"]]

    def merge_by_id(self, this, other): # this, other are "state_id" strings
        # Merge create_state
        for province in self.data[other]["create_state"]:
            found = False
            for province_ref in self.data[this]["create_state"]:
                if province["country"] == province_ref["country"]:
                    found = True
                    province_ref["owned_provinces"] += province["owned_provinces"]
                    break
            if not found:
                self.data[this]["create_state"].append(province)
        # Merge add_homeland
        if "add_homeland" in self.data[other].keys():
            for culture in self.data[other]["add_homeland"]:
                if culture not in self.data[this]["add_homeland"]:
                    self.data[this]["add_homeland"].append(culture)
        # Merge add_claim
        if "add_claim" not in self.data[this].keys():
            if "add_claim" in self.data[other].keys():
                self.data[this]["add_claim"] = self.data[other]["add_claim"]
        elif "add_claim" in self.data[other].keys():
            for country in self.data[other]["add_claim"]:
                if country not in self.data[this]["add_claim"]:
                    self.data[this]["add_claim"].append(country)

    def get_str(self, state_id):
        state_str = f'    {state_id} = {{\n'
        for province in self.data[state_id]["create_state"]:
            state_str += f'        create_state = {{\n'
            state_str += f'            country = {province["country"]}\n'
            state_str += f'            owned_provinces = {{ '
            for owned_province in province["owned_provinces"]:
                state_str += f'{owned_province} '
            state_str += '}\n'
            if "state_type" in province.keys():
                for state_type in province["state_type"]:
                    state_str += f'            state_type = {state_type}\n'
            state_str += '        }\n\n'
        if "add_homeland" in self.data[state_id].keys():
            for culture in self.data[state_id]["add_homeland"]:
                state_str += f'        add_homeland = {culture}\n'
        if "add_claim" in self.data[state_id].keys():
            for country in self.data[state_id]["add_claim"]:
                state_str += f'        add_claim = {country}\n'
        state_str += '    }\n'

        return state_str

    def merge(self, merge_dict):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:"+food) in self.data.keys():
                    print(f'Merging {food} state data into {diner}')
                    self.merge_by_id(("s:"+diner), ("s:"+food))
                    self.data.pop("s:"+food)

    def dump(self, dir):
        with open(dir, 'w', encoding='utf-8-sig') as file:
            file.write('STATES = {\n')
            for state_id in self.data.keys():
                print("Exporting state data: "+state_id)
                file.write(self.get_str(state_id))
            file.write('}\n')

class Trade:
    def __init__(self, trade_dict):
        self.data = trade_dict["TRADE"]
        self.format()

    def format(self):
        # Format trade data to ensure consistent structure
        for state_id in self.data.keys():
            print(f'Formatting trade data: {state_id}')
            if isinstance(self.data[state_id], list):
                merge_dict = {}
                for entry in self.data[state_id]:
                    for region_state, trade_goods in entry.items():
                        if region_state not in merge_dict:
                            merge_dict[region_state] = {}
                        for trade_good, good_data in trade_goods.items():
                            if trade_good not in merge_dict[region_state]:
                                merge_dict[region_state][trade_good] = good_data
                            else:
                                # Merge trade good data
                                merge_dict[region_state][trade_good].update(good_data)
                self.data[state_id] = merge_dict

            # Ensure region_state entries are properly formatted
            for region_state in self.data[state_id].keys():
                if not isinstance(self.data[state_id][region_state], dict):
                    continue

                # Ensure trade goods are properly formatted
                for trade_good in self.data[state_id][region_state].keys():
                    if isinstance(self.data[state_id][region_state][trade_good], dict):
                        # Convert single values to proper structure if needed
                        good_data = self.data[state_id][region_state][trade_good]
                        if 'add_exports' in good_data and not isinstance(good_data['add_exports'], (int, float)):
                            try:
                                good_data['add_exports'] = int(good_data['add_exports'])
                            except (ValueError, TypeError):
                                good_data['add_exports'] = 0
                        if 'add_imports' in good_data and not isinstance(good_data['add_imports'], (int, float)):
                            try:
                                good_data['add_imports'] = int(good_data['add_imports'])
                            except (ValueError, TypeError):
                                good_data['add_imports'] = 0

    def merge_by_id(self, this, other):
        """Merge trade data from 'other' state into 'this' state"""
        if other not in self.data:
            return

        if this not in self.data:
            self.data[this] = {}

        # Merge each region_state from other into this
        for region_state in self.data[other].keys():
            if region_state not in self.data[this]:
                self.data[this][region_state] = {}

            # Merge trade goods for each region_state
            for trade_good in self.data[other][region_state].keys():
                if trade_good not in self.data[this][region_state]:
                    # Copy the entire trade good entry
                    self.data[this][region_state][trade_good] = self.data[other][region_state][trade_good].copy()
                else:
                    # Merge exports and imports
                    other_good = self.data[other][region_state][trade_good]
                    this_good = self.data[this][region_state][trade_good]

                    if 'add_exports' in other_good:
                        if 'add_exports' in this_good:
                            this_good['add_exports'] += other_good['add_exports']
                        else:
                            this_good['add_exports'] = other_good['add_exports']

                    if 'add_imports' in other_good:
                        if 'add_imports' in this_good:
                            this_good['add_imports'] += other_good['add_imports']
                        else:
                            this_good['add_imports'] = other_good['add_imports']

    def merge(self, merge_dict):
        """Merge trade data according to state merging dictionary"""
        for diner, food_list in merge_dict.items():
            for food in food_list:
                food_key = f"s:{food}"
                diner_key = f"s:{diner}"

                if food_key in self.data:
                    print(f'Merging {food} trade data into {diner}')
                    self.merge_by_id(diner_key, food_key)
                    self.data.pop(food_key)

    def get_str(self, state_id):
        """Generate string representation for a state's trade data"""
        if state_id not in self.data:
            return ""

        state_str = f'    {state_id}={{\n'

        for region_state, trade_data in self.data[state_id].items():
            if not trade_data:
                continue

            state_str += f'        {region_state}={{\n'

            for trade_good, good_data in trade_data.items():
                if not good_data:
                    continue

                state_str += f'            {trade_good} = {{\n'

                if 'add_exports' in good_data and good_data['add_exports'] > 0:
                    state_str += f'                add_exports = {good_data["add_exports"]}\n'

                if 'add_imports' in good_data and good_data['add_imports'] > 0:
                    state_str += f'                add_imports = {good_data["add_imports"]}\n'

                state_str += f'            }}\n'

            state_str += f'        }}\n'

        state_str += f'    }}\n'
        return state_str

    def dump(self, dir):
        """Export trade data to file"""
        with open(dir, 'w', encoding='utf-8-sig') as file:
            file.write('TRADE = {\n')
            for state_id in self.data.keys():
                if self.data[state_id]:  # Only write states with trade data
                    print("Exporting trade data: " + state_id)
                    file.write(self.get_str(state_id))
            file.write('}\n')

class StateMerger:
    def __init__(self, game_root_dir, write_dir, merge_dict, cache_dir="./data"):
        self.base_game_dir = {}
        self.mod_dir = {}
        self.game_root_dir = game_root_dir
        self.write_dir = write_dir
        self.merge_dict = merge_dict
        self.cache_dir = cache_dir

        # Set the base game and mod directories
        for key, value in state_file_dir.items():
            self.base_game_dir[key] = self.game_root_dir+value
            self.mod_dir[key] = write_dir+value
        clear_mod_dir(self.mod_dir)

        # Read base game data
        mod_state = ModState(self.base_game_dir, self.mod_dir)
        game_data = {}
        for key in self.base_game_dir.keys():
            game_data[key] = mod_state.get_data(key)

        # Parse data
        self.map_data = MapData(game_data["map_data"])
        self.buildings = Buildings(game_data["buildings"])
        self.pops = Pops(game_data["pops"])
        self.states = States(game_data["state"])
        self.trade = Trade(game_data["trade"])

        # Dump the game_data to a json file
        for key in game_data.keys():
            with open(f"{cache_dir}{key}.json", 'w', encoding='utf-8') as file:
                json.dump(game_data[key], file, indent=4, ensure_ascii=False)

    def merge_state_data(self, buff=True, ignoreSmallStates=False, smallStateLimit=4):
        # Write cleared base game data to mod directory
        for key, value in self.base_game_dir.items():
            for file in os.listdir(value):
                if file == "00_states_merging.txt":
                    continue
                with open(self.mod_dir[key]+file, 'w', encoding='utf-8-sig') as file:
                    file.write("")
        # Delete "/map_data/state_regions/99_sea.txt" in mod directory
        if os.path.exists(self.mod_dir["map_data"]+"99_seas.txt"):
            os.remove(self.mod_dir["map_data"]+"99_seas.txt")

        # Merge map_data
        if not buff:
            ignoreSmallStates = True
            smallStateLimit = 1000
        self.map_data.merge(self.merge_dict, ignoreSmallStates=ignoreSmallStates, smallStateLimit=smallStateLimit)
        self.map_data.dump(self.mod_dir["map_data"]+"00_states_merging.txt")
        # Merge buildings
        self.buildings.merge(self.merge_dict)
        self.buildings.dump(self.mod_dir["buildings"]+"00_states_merging.txt")
        # Merge pops
        self.pops.merge(self.merge_dict)
        self.pops.dump(self.mod_dir["pops"]+"00_states_merging.txt")
        # Merge states
        self.states.merge(self.merge_dict)
        self.states.dump(self.mod_dir["state"]+"00_states.txt")
        # Merge trade
        self.trade.merge(self.merge_dict)
        self.trade.dump(self.mod_dir["trade"]+"00_historical_trade.txt")

    def merge_misc_data(self):
        for dir in replace_file_dir:
            base_game_dir = self.game_root_dir+dir
            mod_dir = self.write_dir+dir
            print("Scanning", base_game_dir)

            # Clear the output directory
            if not os.path.exists(mod_dir):
                os.makedirs(mod_dir)
            else:
                for file in os.listdir(mod_dir):
                    if os.path.isdir(mod_dir+file): # If is folder
                        continue
                    os.remove(os.path.join(mod_dir, file))

            for game_file in os.listdir(base_game_dir):
                if os.path.isdir(base_game_dir+game_file): # If is folder
                    continue

                # Read game file
                with open(base_game_dir+game_file, 'r', encoding='utf-8') as file:
                    lines = file.readlines()

                food_name_found = False

                for diner, food_list in self.merge_dict.items():
                    for food in food_list:
                        # Find all state names in the file
                        if re.search(r'\b' + re.escape(food) + r'\b', ''.join(lines)):
                            food_name_found = True
                            break
                    if food_name_found:
                        break
                if not food_name_found:
                    continue

                print("Modifying", base_game_dir+game_file)
                # Replace all state names with their merged counterparts
                output_file = mod_dir+game_file
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(output_file)):
                    os.makedirs(os.path.dirname(output_file))
                with open(output_file, 'w', encoding='utf-8') as file:
                    for line in lines:
                        for diner, food_list in self.merge_dict.items():
                            for food in food_list:
                                # Replace "food" with "diner"
                                line = re.sub(r'\b' + re.escape(food) + r'\b', diner, line)
                        file.write(line)
        for dir in remove_file_dir:
            base_game_dir = self.game_root_dir+dir
            mod_dir = self.write_dir+dir
            print("Scanning", base_game_dir)

            # Clear the output directory
            if not os.path.exists(mod_dir):
                os.makedirs(mod_dir)
            else:
                for file in os.listdir(mod_dir):
                    if os.path.isdir(mod_dir+file): # If is folder
                        continue
                    os.remove(os.path.join(mod_dir, file))
            
            for game_file in os.listdir(base_game_dir):
                if os.path.isdir(base_game_dir+game_file): # If is folder
                    continue

                # Read game file
                with open(base_game_dir+game_file, 'r', encoding='utf-8') as file:
                    lines = file.readlines()

                food_name_found = False

                for diner, food_list in self.merge_dict.items():
                    for food in food_list:
                        # Find all state names in the file
                        if re.search(r'\b' + re.escape(food) + r'\b', ''.join(lines)):
                            food_name_found = True
                            break
                    if food_name_found:
                        break
                if not food_name_found:
                    continue

                print("Modifying", base_game_dir+game_file)
                # Replace all state names with ""
                output_file = mod_dir+game_file
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(output_file)):
                    os.makedirs(os.path.dirname(output_file))
                with open(output_file, 'w', encoding='utf-8') as file:
                    for line in lines:
                        for diner, food_list in self.merge_dict.items():
                            for food in food_list:
                                # Replace "food" with ""
                                line = re.sub(r'\b' + re.escape(food) + r'\b', "", line)
                        file.write(line)

        # Copy state_trait file to mod directory
        dir = f"{self.write_dir}common/state_traits"
        file = f"{self.cache_dir}state_traits.txt"
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(dir+"/00_states_merging.txt"):
            os.remove(dir+"/00_states_merging.txt")
        shutil.copy(file, dir+"/00_states_merging.txt")

        # Copy USA flag adaptation file to mod directory
        dir = f"{self.write_dir}common/flag_definitions"
        file = f"{self.cache_dir}01_flag_definitions_usa.txt"
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(dir+"/01_flag_definitions_usa.txt"):
            os.remove(dir+"/01_flag_definitions_usa.txt")
        shutil.copy(file, dir)

        # Copy USA state counting file to mod directory
        dir = f"{self.write_dir}common/script_values"
        file = f"{self.cache_dir}usa_state_counter.txt"
        if not os.path.exists(dir):
            os.makedirs(dir)
        # Delete the file in dir if it exists
        if os.path.exists(dir+"/00_states_merging.txt"):
            os.remove(dir+"/00_states_merging.txt")
        shutil.copy(file, dir+"/00_states_merging.txt")

    def merge_loc_data(self):
        # Read localization yml files
        for lang, loc_dir in loc_file_dir.items():
            print(f"Reading localization files for {lang}...")
            hub_file = os.path.join(self.game_root_dir, loc_dir, f'hub_names_{lang}.yml')
            miss_dict = {}
            with open(hub_file, 'r', encoding='utf-8') as f:
                cleaned_yml = clean_v3_yml_numbered_keys(hub_file)
                data = yaml.safe_load(cleaned_yml)[lang]
                # Process the localization data as needed
                print(f"Processing {hub_file} for {lang}")
                for diner, food_list in self.merge_dict.items():
                    # Skip states with empty food lists (no merging needed)
                    if not food_list:
                        continue
                    
                    # Check if the diner state exists in map data
                    if diner not in self.map_data.data:
                        print(f"Warning: {diner} not found in map data, skipping localization processing")
                        continue
                    
                    # Check if city, wood, mine, farm, port attribute of diner are in the localization data
                    for attr in ["city", "wood", "mine", "farm", "port"]:
                        if getattr(self.map_data.data[diner], attr, '') == '':
                            continue
                        if f"HUB_NAME_{diner}_{attr}" in data.keys():
                            continue
                        # If not found, add a missing hub name entry
                        print(f"Missing HUB_NAME_{diner}_{attr} in {lang}")
                        # Search for attribute in the food_list
                        for food in food_list:
                            if f"HUB_NAME_{food}_{attr}" in data.keys():
                                miss_dict[f"HUB_NAME_{diner}_{attr}"] = "\""+data[f'HUB_NAME_{food}_{attr}']+"\""
                                print(miss_dict[f"HUB_NAME_{diner}_{attr}"])
                                break
            # Write the missing hub names to the localization file
            write_file = self.write_dir + loc_dir + f'hub_names_states_merging_{lang}.yml'
            if miss_dict:
                print(f'Modifying {write_file}')
                # Create the output directory if it doesn't exist
                if not os.path.exists(os.path.dirname(write_file)):
                    os.makedirs(os.path.dirname(write_file))
                with open(write_file, 'w', encoding='utf-8-sig') as f:
                    content = yaml.dump({lang: miss_dict}, allow_unicode=True, default_style='', default_flow_style=False)
                    # Remove all '\'' in write_file
                    content = content.replace("'", "")
                    f.write(content)