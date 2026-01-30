from pyradox import Tree

seq_str = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]


class stateregion:
    """Class for state objects in '/map_data/state_regions/'
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
    """

    def __init__(self, name, dict):
        """Initialize the state object with a dictionary"""
        self.name = ""
        self.id = 0
        self.subsistence_building = ""
        self.provinces = []
        self.impassable = []
        self.prime_land = []
        self.traits = []
        self.city = ""
        self.port = ""
        self.farm = ""
        self.mine = ""
        self.wood = ""
        self.arable_land = 0
        self.arable_resources = []
        self.capped_resources = {}
        self.gold = [0, 0]  # gold[0]: undiscovered, gold[1]: discovered
        self.rubber = [0, 0]  # rubber[0]: undiscovered, rubber[1]: discovered
        self.oil = 0
        self.naval_exit_id = -1

        self.name = name
        dict_data = dict[name]
        self.id = int(dict_data["id"])
        if "subsistence_building" not in dict_data.keys():  # Check if is sea node
            self.subsistence_building = ""
            self.provinces = dict_data["provinces"]
            return
        self.subsistence_building = dict_data["subsistence_building"]
        self.provinces = dict_data["provinces"]
        if "impassable" in dict_data.keys():
            self.impassable = dict_data["impassable"]
        else:
            self.impassable = []
        if "prime_land" in dict_data.keys():
            self.prime_land = dict_data["prime_land"]
        else:
            self.prime_land = []
        if "traits" in dict_data.keys():
            self.traits = dict_data["traits"]
        else:
            self.traits = []
        if "city" in dict_data.keys():
            self.city = dict_data["city"]
        else:
            self.city = ""
        if "port" in dict_data.keys():
            self.port = dict_data["port"]
        else:
            self.port = ""
        if "farm" in dict_data.keys():
            self.farm = dict_data["farm"]
        else:
            self.farm = ""
        if "mine" in dict_data.keys():
            self.mine = dict_data["mine"]
        else:
            self.mine = ""
        if "wood" in dict_data.keys():
            self.wood = dict_data["wood"]
        else:
            self.wood = ""
        self.arable_land = int(dict_data["arable_land"])
        self.arable_resources = dict_data["arable_resources"]
        self.capped_resources = {}
        if "capped_resources" in dict_data.keys():
            for resource, amount in dict_data["capped_resources"].items():
                self.capped_resources[resource] = int(amount)
        if "resource" in dict_data.keys():
            if not isinstance(dict_data["resource"], list):
                dict_data["resource"] = [dict_data["resource"]]
            for resource in dict_data["resource"]:
                if resource["type"] == "building_gold_field":
                    self.gold[0] = int(resource["undiscovered_amount"])
                    if "discovered_amount" in resource.keys():
                        self.gold[1] = int(resource["discovered_amount"])
                elif resource["type"] == "building_rubber_plantation":
                    if "undiscovered_amount" in resource.keys():
                        self.rubber[0] = int(resource["undiscovered_amount"])
                    if "discovered_amount" in resource.keys():
                        self.rubber[1] = int(resource["discovered_amount"])
                elif resource["type"] == "building_oil_rig":
                    self.oil = int(resource["undiscovered_amount"])
                else:
                    print(f'Unknown resource type: {resource["type"]}')
        if "naval_exit_id" in dict_data.keys():
            self.naval_exit_id = dict_data["naval_exit_id"]
        else:
            self.naval_exit_id = -1

    def merge_states_cnt(self):
        """Determine the number of states merged in the state"""
        if self.is_sea_node():
            return 0
        for i in range(2, 9):
            if f"state_trait_{seq_str[i]}_states_integration" in self.traits:
                return i
        return 1

    def merge_coast_cnt(self):
        """Determine the number of coast states merged in the state"""
        if self.is_sea_node():
            return 0
        if self.naval_exit_id == -1:
            return 0
        for i in range(2, 7):
            if f"state_trait_{seq_str[i]}_coast_integration" in self.traits:
                return i
        return 1

    def is_sea_node(self):
        """Determine if the state is a sea node"""
        if self.subsistence_building == "":
            return True
        return False

    def province_cnt(self):
        """Return the number of provinces in the state"""
        return len(self.provinces)

    def is_small_state(self, limit=4):
        """Determine if the state is a small state"""
        if self.is_sea_node():
            return False
        if self.province_cnt() < limit:
            return True
        return False

    def merge(self, other, ignoreSmallStates=False, smallStateLimit=4):
        """Merge two state objects."""
        if self.is_sea_node() or other.is_sea_node():
            print(f"Error: Cannot merge sea node with other state")
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
            self.traits.remove(
                f"state_trait_{seq_str[thisMergeStatesCnt]}_states_integration"
            )
        if thisCoastCnt > 1:
            self.traits.remove(f"state_trait_{seq_str[thisCoastCnt]}_coast_integration")
        for trait in other.traits:
            if (
                trait
                != f"state_trait_{seq_str[otherMergeStatesCnt]}_states_integration"
                and trait != f"state_trait_{seq_str[otherCoastCnt]}_coast_integration"
                and trait not in self.traits
            ):
                self.traits.append(trait)
        totalMergeStatesCnt = thisMergeStatesCnt + otherMergeStatesCnt
        totalCoastCnt = thisCoastCnt + otherCoastCnt
        if ignoreSmallStates:
            if self.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
                totalCoastCnt -= 1
            if other.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
                totalCoastCnt -= 1
        if (totalMergeStatesCnt > 1) and (totalMergeStatesCnt < 8):
            self.traits.append(
                f"state_trait_{seq_str[totalMergeStatesCnt]}_states_integration"
            )
        elif totalMergeStatesCnt >= 8:
            self.traits.append("state_trait_eight_states_integration")
        if (totalCoastCnt > 1) and (totalCoastCnt < 6):
            self.traits.append(
                f"state_trait_{seq_str[totalCoastCnt]}_coast_integration"
            )
        elif totalCoastCnt >= 6:
            self.traits.append("state_trait_six_coast_integration")
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
        if self.port == "":
            self.port = other.port
        if self.mine == "":
            self.mine = other.mine
        if self.wood == "":
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
        """Export the state object to a string"""
        state_str = f"{self.name} = {{\n"
        state_str += f"    id = {self.id}\n"
        if self.is_sea_node():
            state_str += f"    provinces = {{ "
            for province in self.provinces:
                state_str += f"{province} "
            state_str += f"}}\n"
            state_str += f"}}\n\n"
            return state_str
        state_str += f"    subsistence_building = {self.subsistence_building}\n"
        state_str += f"    provinces = {{ "
        for province in self.provinces:
            state_str += f"{province} "
        state_str += f"}}\n"
        if self.impassable != []:
            state_str += f"    impassable = {{ "
            for province in self.impassable:
                state_str += f"{province} "
            state_str += f"}}\n"
        if self.prime_land != []:
            state_str += f"    prime_land = {{ "
            for province in self.prime_land:
                state_str += f"{province} "
            state_str += f"}}\n"
        if self.traits != []:
            state_str += f"    traits = {{ "
            for trait in self.traits:
                state_str += f"{trait} "
            state_str += f"}}\n"
        if self.city != "":
            state_str += f"    city = {self.city}\n"
        if self.port != "":
            state_str += f"    port = {self.port}\n"
        if self.farm != "":
            state_str += f"    farm = {self.farm}\n"
        if self.mine != "":
            state_str += f"    mine = {self.mine}\n"
        if self.wood != "":
            state_str += f"    wood = {self.wood}\n"
        state_str += f"    arable_land = {self.arable_land}\n"
        state_str += f"    arable_resources = {{ "
        for resource in self.arable_resources:
            state_str += f"{resource} "
        state_str += f"}}\n"
        if self.capped_resources:
            state_str += f"    capped_resources = {{\n"
            for resource, amount in self.capped_resources.items():
                state_str += f"        {resource} = {amount}\n"
            state_str += f"    }}\n"
        if self.gold != [0, 0]:
            state_str += f"    resource = {{\n"
            state_str += f'        type = "building_gold_field"\n'
            state_str += f'        depleted_type = "building_gold_mine"\n'
            if self.gold[0] != 0:
                state_str += f"        undiscovered_amount = {self.gold[0]}\n"
            if self.gold[1] != 0:
                state_str += f"        discovered_amount = {self.gold[1]}\n"
            state_str += f"    }}\n"
        if self.rubber != [0, 0]:
            state_str += f"    resource = {{\n"
            state_str += f'        type = "building_rubber_plantation"\n'
            if self.rubber[0] != 0:
                state_str += f"        undiscovered_amount = {self.rubber[0]}\n"
            if self.rubber[1] != 0:
                state_str += f"        discovered_amount = {self.rubber[1]}\n"
            state_str += f"    }}\n"
        if self.oil != 0:
            state_str += f"    resource = {{\n"
            state_str += f'        type = "building_oil_rig"\n'
            state_str += f"        undiscovered_amount = {self.oil}\n"
            state_str += f"    }}\n"
        if self.naval_exit_id != -1:
            state_str += f"    naval_exit_id = {self.naval_exit_id}\n"
        state_str += f"}}\n\n"

        return state_str

    def to_python(self):
        """Export the state object to a Python dictionary"""
        state_dict = {}
        state_dict["id"] = self.id
        state_dict["provinces"] = self.provinces
        if self.is_sea_node():
            return state_dict
        state_dict["subsistence_building"] = self.subsistence_building
        if self.impassable != []:
            state_dict["impassable"] = self.impassable
        if self.prime_land != []:
            state_dict["prime_land"] = self.prime_land
        if self.traits != []:
            state_dict["traits"] = self.traits
        if self.city != "":
            state_dict["city"] = self.city
        if self.port != "":
            state_dict["port"] = self.port
        if self.farm != "":
            state_dict["farm"] = self.farm
        if self.mine != "":
            state_dict["mine"] = self.mine
        if self.wood != "":
            state_dict["wood"] = self.wood
        state_dict["arable_land"] = self.arable_land
        state_dict["arable_resources"] = self.arable_resources
        if self.capped_resources:
            state_dict["capped_resources"] = self.capped_resources
        resources_list = []
        if self.gold != [0, 0]:
            gold_resource = {}
            gold_resource["type"] = "building_gold_field"
            gold_resource["depleted_type"] = "building_gold_mine"
            if self.gold[0] != 0:
                gold_resource["undiscovered_amount"] = self.gold[0]
            if self.gold[1] != 0:
                gold_resource["discovered_amount"] = self.gold[1]
            resources_list.append(gold_resource)
        if self.rubber != [0, 0]:
            rubber_resource = {}
            rubber_resource["type"] = "building_rubber_plantation"
            if self.rubber[0] != 0:
                rubber_resource["undiscovered_amount"] = self.rubber[0]
            if self.rubber[1] != 0:
                rubber_resource["discovered_amount"] = self.rubber[1]
            resources_list.append(rubber_resource)
        if self.oil != 0:
            oil_resource = {}
            oil_resource["type"] = "building_oil_rig"
            oil_resource["undiscovered_amount"] = self.oil
            resources_list.append(oil_resource)
        if resources_list != []:
            state_dict["resource"] = resources_list
        if self.naval_exit_id != -1:
            state_dict["naval_exit_id"] = self.naval_exit_id
        return state_dict


class StateRegion(dict):
    """
    Dictionary of stateregion objects
    """

    def __init__(self, source=None):
        if source is None:
            super().__init__()
        elif isinstance(source, Tree):
            source_dict = source.to_python()
            for state_id in source_dict.keys():
                self[state_id] = stateregion(state_id, source_dict)
        elif isinstance(source, dict):
            for state_id in source.keys():
                self[state_id] = stateregion(state_id, source)
        else:
            raise TypeError(
                "StateRegion can only be initialized with a Tree object, a dict, or None"
            )

    def merge_state(
        self, diner, food, ignoreSmallStates=False, smallStateLimit=4
    ):
        self[diner].merge(
            self[food],
            ignoreSmallStates=ignoreSmallStates,
            smallStateLimit=smallStateLimit,
        )
        self.pop(food)

    def merge_states(self, merge_dict, ignoreSmallStates=False, smallStateLimit=4):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                self.merge_state(
                    diner,
                    food,
                    ignoreSmallStates=ignoreSmallStates,
                    smallStateLimit=smallStateLimit,
                )

    def __str__(self, include_sea_nodes=False):
        state_str = ""
        for stateregion in self.values():
            if not include_sea_nodes and stateregion.is_sea_node():
                continue
            state_str += str(stateregion)
        return state_str

    def dump(self, dir, include_sea_nodes=False):
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(self.__str__(include_sea_nodes=include_sea_nodes))

    def provinces_count_dict(self):
        """Return a dictionary of province counts for each state"""
        count_dict = {}
        for state_id, state in self.items():
            count_dict[state_id] = state.province_cnt()
        return count_dict

    def to_python(self):
        """Export the StateRegion object to a Python dictionary"""
        state_region_dict = {}
        for state_id, state in self.items():
            state_region_dict[state_id] = state.to_python()
        return state_region_dict
