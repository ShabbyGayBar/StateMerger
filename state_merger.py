from paradox_file_parser import ParadoxFileParser
import os
import re
import json
import shutil

state_file_dir = {
    "map_data": r"map_data/state_regions/",
    "state": r"common/history/states/",
    "pops": r"common/history/pops/",
    "buildings": r"common/history/buildings/"
}

misc_file_dir = [
    "common/ai_strategies/",
    "common/buildings/",
    "common/canals/"
    "common/character_templates/",
    "common/company_types/",
    "common/country_creation/",
    "common/country_definitions/",
    "common/country_formation/",
    "common/decisions/",
    "common/dynamic_country_names/",
    "common/flag_definitions/",
    "common/history/countries/"
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

filename = "00_states_merging.txt"
seq_str = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]
smallStateLimit = 4 # The limit of provinces for a state to be considered a small state

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
        # print(dict_data)
        self.id = int(dict_data['id'])
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
                # print(resource, amount)
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
        for i in range(2, 9):
            if f'"state_trait_{seq_str[i]}_states_integration"' in self.traits:
                return i
        return 1
    
    def merge_coast_cnt(self):
        '''Determine the number of coast states merged in the state
        '''
        if self.naval_exit_id == -1:
            return 0
        for i in range(2, 7):
            if f'"state_trait_{seq_str[i]}_coast_integration"' in self.traits:
                return i
        return 1

    def province_cnt(self):
        '''Return the number of provinces in the state
        '''
        return len(self.provinces)

    def is_small_state(self):
        '''Determine if the state is a small state
        '''
        if self.province_cnt() < smallStateLimit:
            return True
        return False

    def merge(self, other, ignoreSmallStates=False):
        '''Merge two state objects.
        '''
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
            if self.is_small_state():
                totalMergeStatesCnt -= 1
                totalCoastCnt -= 1
            if other.is_small_state():
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
            if "subsistence_building" not in states_dict[state_id].keys(): # Check if is sea state
                print(f'{state_id} is a sea state, skipping...')
                continue
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

    def merge(self, merge_dict, ignoreSmallStates=False):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if food in self.data.keys():
                    print(f'Merging {food} map_data into {diner}')
                    self.data[diner].merge(self.data[food], ignoreSmallStates)
                    self.data.pop(food)

    def dump(self, dir):
        with open(dir, 'w', encoding='utf_8_sig') as file:
            for state_id in self.data.keys():
                print("Exporting map_data: "+state_id)
                file.write(str(self.data[state_id]))

class Buildings:
    def __init__(self, buildings_dict):
        self.data = buildings_dict["BUILDINGS"]
        self.format()

    def format(self):
        for state_id in self.data.keys(): # Restore the original structure of certain building keys
            if state_id == "if":
                continue
            print(f'Formatting building data: {state_id}')
            for tag in self.data[state_id].keys():
                if not isinstance(self.data[state_id][tag], dict):
                    self.data[state_id][tag] = {"create_building": []}
                    continue
                if isinstance(self.data[state_id][tag]["create_building"], tuple):
                    self.data[state_id][tag]["create_building"] = list(self.data[state_id][tag]["create_building"])
                elif not isinstance(self.data[state_id][tag]["create_building"], list):
                    self.data[state_id][tag]["create_building"] = [self.data[state_id][tag]["create_building"]]
                for building in self.data[state_id][tag]["create_building"]:
                    if 'add_ownership' in building.keys():
                        if "building" in building["add_ownership"].keys():
                            if isinstance(building["add_ownership"]["building"], tuple):
                                building["add_ownership"]["building"] = list(building["add_ownership"]["building"])
                            elif not isinstance(building["add_ownership"]['building'], list):
                                building["add_ownership"]['building'] = [building["add_ownership"]['building']]
                        if "country" in building["add_ownership"].keys():
                            if isinstance(building["add_ownership"]["country"], tuple):
                                building["add_ownership"]["country"] = list(building["add_ownership"]["country"])
                            elif not isinstance(building["add_ownership"]['country'], list):
                                building["add_ownership"]['country'] = [building["add_ownership"]['country']]
                        if "company" in building["add_ownership"].keys():
                            if isinstance(building["add_ownership"]["company"], tuple):
                                building["add_ownership"]["company"] = list(building["add_ownership"]["company"])
                            elif not isinstance(building["add_ownership"]['company'], list):
                                building["add_ownership"]['company'] = [building["add_ownership"]['company']]

    def merge_by_id(self, this, other): # this, other are "state_id" strings
    # state_id layer
        # tag layer
        for tag in self.data[other].keys():
            if not isinstance(self.data[other][tag], dict): # self.data[other][tag] is not dict
                continue # skip this tag because there's no building data
            if (tag not in self.data[this].keys()) or (not isinstance(self.data[this][tag], dict)): # tag exists in self.data[this] but is empty or tag doesn't exist in self.data[this] at all
                self.data[this][tag] = self.data[other][tag]
                continue
            # create_building layer
            for other_building in self.data[other][tag]["create_building"]:
                found = False
                for this_building in self.data[this][tag]["create_building"]:
                    # building layer
                    if this_building["building"] == other_building["building"]:
                        found = True
                        if "building" in other_building["add_ownership"].keys():
                            if "building" in this_building["add_ownership"].keys():
                                for other_ownership in other_building["add_ownership"]["building"]:
                                    found_ownership = False
                                    for this_ownership in this_building["add_ownership"]["building"]:
                                        # if "type", "country", "region" are the same, merge "levels"
                                        if this_ownership["type"] == other_ownership["type"] and this_ownership["country"] == other_ownership["country"] and this_ownership["region"] == other_ownership["region"]:
                                            found_ownership = True
                                            this_ownership["levels"] = int(this_ownership["levels"]) + int(other_ownership["levels"])
                                            break
                                    if not found_ownership:
                                        this_building["add_ownership"]["building"].append(other_ownership)
                            else:
                                this_building["add_ownership"]["building"] = other_building["add_ownership"]["building"]
                        if "country" in other_building["add_ownership"].keys():
                            if "country" in this_building["add_ownership"].keys():
                                for other_ownership in other_building["add_ownership"]["country"]:
                                    found_ownership = False
                                    for this_ownership in this_building["add_ownership"]["country"]:
                                        # if "country" is the same, merge "levels"
                                        if this_ownership["country"] == other_ownership["country"]:
                                            found_ownership = True
                                            this_ownership["levels"] = int(this_ownership["levels"]) + int(other_ownership["levels"])
                                            break
                                    if not found_ownership:
                                        this_building["add_ownership"]["country"].append(other_ownership)
                            else:
                                this_building["add_ownership"]["country"] = other_building["add_ownership"]["country"]
                        if "company" in other_building["add_ownership"].keys():
                            if "company" in this_building["add_ownership"].keys():
                                for other_ownership in other_building["add_ownership"]["company"]:
                                    found_ownership = False
                                    for this_ownership in this_building["add_ownership"]["company"]:
                                        # if "type", "country" are the same, merge "levels"
                                        if this_ownership["type"] == other_ownership["type"] and this_ownership["country"] == other_ownership["country"]:
                                            found_ownership = True
                                            this_ownership["levels"] = int(this_ownership["levels"]) + int(other_ownership["levels"])
                                            break
                                    if not found_ownership:
                                        this_building["add_ownership"]["company"].append(other_ownership)
                        break
                if not found:
                    self.data[this][tag]["create_building"].append(other_building)

    def merge(self, merge_dict):
        # Merge building ownerships
        for state_id in self.data.keys():
            if state_id == "if":
                continue
            for tag in self.data[state_id].keys():
                if not isinstance(self.data[state_id][tag], dict):
                    continue
                for building in self.data[state_id][tag]["create_building"]:
                    if "add_ownership" not in building.keys():
                        continue
                    if "building" not in building["add_ownership"].keys():
                        continue
                    for owner in building["add_ownership"]["building"]:
                        region = owner["region"].replace('\"', '') # Remove '\"' from owner["region"]
                        for diner, food_list in merge_dict.items():
                            if region in food_list:
                                owner["region"] = '\"'+diner+'\"'
                                break
        # Merge building
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:"+food) in self.data.keys():
                    print(f'Merging {food} building data into {diner}')
                    self.merge_by_id("s:"+diner, "s:"+food)
                    self.data.pop("s:"+food)

    def get_str(self, state_id):
        if state_id == "if":
            return ""
        building_str = f'    {state_id} = {{\n'
        for tag in self.data[state_id].keys():
            building_str += f'        {tag} = {{\n'
            if isinstance(self.data[state_id][tag], dict):
                for building in self.data[state_id][tag]["create_building"]:
                    building_str += f'            create_building = {{\n'
                    building_str += f'                building = {building["building"]}\n'
                    if "add_ownership" not in building.keys(): # is monument, only has key "building" & "level"
                        building_str += f'                level = {building["level"]}\n'
                        building_str += f'            }}\n'
                        continue
                    building_str += f'                add_ownership = {{\n'
                    # print(name, building["building"], building.keys())
                    if "building" in building["add_ownership"].keys():
                        # in case of multiple ownerships, we need to iterate through each ownership
                        for ownership in building["add_ownership"]["building"]:
                            building_str += f'                    building = {{\n'
                            building_str += f'                        type = {ownership["type"]}\n'
                            building_str += f'                        country = {ownership["country"]}\n'
                            building_str += f'                        levels = {ownership["levels"]}\n'
                            building_str += f'                        region = {ownership["region"]}\n'
                            building_str += f'                    }}\n'
                    if "country" in building["add_ownership"].keys():
                        for ownership in building["add_ownership"]["country"]:
                            building_str += f'                    country = {{\n'
                            building_str += f'                        country = {ownership["country"]}\n'
                            building_str += f'                        levels = {ownership["levels"]}\n'
                            building_str += f'                    }}\n'
                    if "company" in building["add_ownership"].keys():
                        for ownership in building["add_ownership"]["company"]:
                            building_str += f'                    company = {{\n'
                            building_str += f'                        type = {ownership["type"]}\n'
                            building_str += f'                        country = {ownership["country"]}\n'
                            building_str += f'                        levels = {ownership["levels"]}\n'
                            building_str += f'                    }}\n'
                    building_str += f'                }}\n'
                    # Building cash reserve
                    if "reserves" in building.keys():
                        building_str += f'                reserves = {building["reserves"]}\n'
                    # Building production methodss
                    if "activate_production_methods" in building.keys():
                        building_str += f'                activate_production_methods = {{\n'
                        if isinstance(building["activate_production_methods"], str):
                            building_str += f'                    {building["activate_production_methods"]}\n'
                        else:
                            for method in building["activate_production_methods"]:
                                building_str += f'                    {method}\n'
                        building_str += f'                }}\n'
                    building_str += f'            }}\n'
            building_str += f'        }}\n'
        building_str += f'    }}\n'

        return building_str

    def dump(self, dir):
        with open(dir, 'w', encoding='utf_8_sig') as file:
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
        with open(dir, 'w', encoding='utf_8_sig') as file:
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
        with open(dir, 'w', encoding='utf_8_sig') as file:
            file.write('STATES = {\n')
            for state_id in self.data.keys():
                print("Exporting state data: "+state_id)
                file.write(self.get_str(state_id))
            file.write('}\n')

class StateMerger:
    def __init__(self, game_root_dir, merge_dict):
        self.base_game_dir = {}
        self.mod_dir = {}
        self.game_root_dir = game_root_dir
        self.merge_dict = merge_dict

        # Set the base game and mod directories
        for key, value in state_file_dir.items():
            self.base_game_dir[key] = self.game_root_dir+value
            self.mod_dir[key] = r"./mod/"+value
        self.clear_mod_dir()
                
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

        # Dump the game_data to a json file
        with open("./data/game_data.json", 'w', encoding='utf_8') as file:
            json.dump(game_data, file, indent=4, ensure_ascii=False)

    def clear_mod_dir(self):
        # Clear the output directory
        for dir in self.mod_dir.values():
            if not os.path.exists(dir):
                os.makedirs(dir)
            else:
                for file in os.listdir(dir):
                    os.remove(os.path.join(dir, file))

    def merge_state_data(self, ignoreSmallStates=False):
        # Write cleared base game data to mod directory
        for key, value in self.base_game_dir.items():
            for file in os.listdir(value):
                if file == filename:
                    continue
                with open(self.mod_dir[key]+file, 'w', encoding='utf_8_sig') as file:
                    file.write("")
        # Delete "/map_data/state_regions/99_sea.txt" in mod directory
        if os.path.exists(self.mod_dir["map_data"]+"99_seas.txt"):
            os.remove(self.mod_dir["map_data"]+"99_seas.txt")

        # Merge map_data
        self.map_data.merge(self.merge_dict, ignoreSmallStates)
        self.map_data.dump(self.mod_dir["map_data"]+filename)
        # Merge buildings
        self.buildings.merge(self.merge_dict)
        self.buildings.dump(self.mod_dir["buildings"]+filename)
        # Merge pops
        self.pops.merge(self.merge_dict)
        self.pops.dump(self.mod_dir["pops"]+filename)
        # Merge states
        self.states.merge(self.merge_dict)
        self.states.dump(self.mod_dir["state"]+"00_states.txt")

        # Copy state_trait file to mod directory
        state_trait_dir = "./mod/common/state_traits"
        state_trait_file = "./data/00_states_merging.txt"
        if not os.path.exists(state_trait_dir):
            os.makedirs(state_trait_dir)
        # Delete the file in state_trait_dir if it exists
        if os.path.exists(state_trait_dir+"/"+filename):
            os.remove(state_trait_dir+"/"+filename)
        shutil.copy(state_trait_file, state_trait_dir)

    def merge_misc_data(self):
        for dir in misc_file_dir:
            base_game_dir = self.game_root_dir+dir
            mod_dir = r"./mod/"+dir
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
                with open(output_file, 'w', encoding='utf_8') as file:
                    for line in lines:
                        for diner, food_list in self.merge_dict.items():
                            for food in food_list:
                                # Replace "food" with "diner"
                                line = re.sub(r'\b' + re.escape(food) + r'\b', diner, line)
                        file.write(line)

