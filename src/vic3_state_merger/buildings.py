from pyradox import Tree


def format_dict_to_string(d, indent_level=0):
    # Convert self into the game's file format and write to file_path
    lines = []
    for key, value in d.items() if isinstance(d, dict) else enumerate(d):
        if value is None:
            continue
        if isinstance(value, dict):
            lines.append("    " * indent_level + f"{key} = {{")
            lines.append(format_dict_to_string(value, indent_level + 1))
            lines.append("    " * indent_level + f"}}")
        elif isinstance(value, list):
            lines.append("    " * indent_level + f"{key} = {{")
            for item in value:
                if isinstance(item, (dict, list)):
                    lines.append(format_dict_to_string(item, indent_level + 1))
                else:
                    lines.append("    " * (indent_level + 1) + f"{item}")
            lines.append("    " * indent_level + f"}}")
        else:
            lines.append("    " * indent_level + f"{key} = {value}")

    return "\n".join(lines)


class Building:
    def __init__(self, dict):
        """Initialize the building object with a dictionary"""
        if "building" in dict.keys():
            self.building = dict["building"]
        else:
            self.building = None
        self.building_ownership = []
        self.country_ownership = []
        self.company_ownership = []
        self.reserves = 0
        self.activate_production_methods = []
        self.isMonument = "level" in dict.keys()
        if self.isMonument:
            return
        if "add_ownership" in dict.keys():
            if isinstance(dict["add_ownership"], list):
                for ownership_dict in dict["add_ownership"]:
                    self.add_ownership(ownership_dict)
            else:
                self.add_ownership(dict["add_ownership"])
        if "reserves" in dict.keys():
            self.reserves = int(dict["reserves"])
        if "activate_production_methods" in dict.keys():
            self.activate_production_methods = dict["activate_production_methods"]
        self.refresh()

    def add_ownership(self, ownership_dict):
        """Add ownerships from a dictionary"""
        if "building" in ownership_dict.keys():
            if not isinstance(ownership_dict["building"], list):
                self.building_ownership.append(ownership_dict["building"])
            else:
                self.building_ownership.extend(ownership_dict["building"])
        if "country" in ownership_dict.keys():
            if not isinstance(ownership_dict["country"], list):
                self.country_ownership.append(ownership_dict["country"])
            else:
                self.country_ownership.extend(ownership_dict["country"])
        if "company" in ownership_dict.keys():
            if not isinstance(ownership_dict["company"], list):
                self.company_ownership.append(ownership_dict["company"])
            else:
                self.company_ownership.extend(ownership_dict["company"])

    def is_empty(self):
        """Check if the building object is empty"""
        if self.building is None:
            return True
        if self.isMonument:
            return False
        if (
            not self.building_ownership
            and not self.country_ownership
            and not self.company_ownership
        ):
            return True
        return False

    def refresh(self):
        """Sort ownerships and merge duplicate ownerships"""
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
                if (
                    this_ownership["type"] == other_ownership["type"]
                    and this_ownership["country"] == other_ownership["country"]
                    and this_ownership["region"] == other_ownership["region"]
                ):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        other_ownership["levels"]
                    )
                    break
            if not found:
                sorted_ownership.append(other_ownership)
        self.building_ownership = sorted_ownership
        if not isinstance(self.activate_production_methods, list):
            self.activate_production_methods = [self.activate_production_methods]

    def level_cnt(self):
        if self.isMonument:
            return 1
        levels = 0
        for ownership in (
            self.building_ownership + self.country_ownership + self.company_ownership
        ):
            levels += int(ownership["levels"])
        return levels

    def __iadd__(self, other):
        """Add two building objects together"""
        if self.building != other.building:
            raise ValueError("Cannot add buildings with different types")
        for ownership in other.building_ownership:
            found = False
            for this_ownership in self.building_ownership:
                if (
                    this_ownership["type"] == ownership["type"]
                    and this_ownership["country"] == ownership["country"]
                    and this_ownership["region"] == ownership["region"]
                ):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
                    break
            if not found:
                self.building_ownership.append(ownership)
        for ownership in other.country_ownership:
            found = False
            for this_ownership in self.country_ownership:
                if this_ownership["country"] == ownership["country"]:
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
                    break
            if not found:
                self.country_ownership.append(ownership)
        for ownership in other.company_ownership:
            found = False
            for this_ownership in self.company_ownership:
                if (
                    this_ownership["type"] == ownership["type"]
                    and this_ownership["country"] == ownership["country"]
                ):
                    found = True
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
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
            building_str += (
                f"                        country = {ownership['country']}\n"
            )
            building_str += f"                        levels = {ownership['levels']}\n"
            building_str += f"                        region = {ownership['region']}\n"
            building_str += f"                    }}\n"
        for ownership in self.country_ownership:
            building_str += f"                    country = {{\n"
            building_str += (
                f"                        country = {ownership['country']}\n"
            )
            building_str += f"                        levels = {ownership['levels']}\n"
            building_str += f"                    }}\n"
        for ownership in self.company_ownership:
            building_str += f"                    company = {{\n"
            building_str += f"                        type = {ownership['type']}\n"
            building_str += (
                f"                        country = {ownership['country']}\n"
            )
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


class Buildings(dict):
    def __init__(self, source):
        super().__init__()
        if source is None:
            return
        elif isinstance(source, Tree):
            buildings_dict = source.to_python()
        elif isinstance(source, dict):
            buildings_dict = source
        else:
            raise TypeError(
                "Buildings can only be initialized with a Tree object, a dict, or None"
            )
        for state_id in buildings_dict["BUILDINGS"].keys():
            if state_id == "if":  # dlc buildings
                self["if"] = buildings_dict["BUILDINGS"]["if"]  # dlc buildings
                continue
            print("Reading buildings: " + state_id)
            self[state_id] = {}
            for tag in buildings_dict["BUILDINGS"][state_id].keys():
                self[state_id][tag] = []
                if (
                    not isinstance(buildings_dict["BUILDINGS"][state_id][tag], dict)
                ) or (
                    "create_building"
                    not in buildings_dict["BUILDINGS"][state_id][tag].keys()
                ):
                    continue
                if not isinstance(
                    buildings_dict["BUILDINGS"][state_id][tag]["create_building"], list
                ):
                    buildings_dict["BUILDINGS"][state_id][tag]["create_building"] = [
                        buildings_dict["BUILDINGS"][state_id][tag]["create_building"]
                    ]
                for building in buildings_dict["BUILDINGS"][state_id][tag][
                    "create_building"
                ]:
                    self[state_id][tag].append(Building(building))
        self.format()

    def format(self):
        for (
            state_id
        ) in self.keys():  # Restore the original structure of certain building keys
            if state_id == "if":
                continue
            for tag in self[state_id].keys():
                for i in range(len(self[state_id][tag]), 0, -1):
                    if self[state_id][tag][i - 1].is_empty():
                        self[state_id][tag].pop(i - 1)

    def merge_state(self, diner, food):
        if ("s:" + food) in self.keys():
            # print(f"Merging {food} building data into {diner}")
            for tag in self["s:" + food].keys():
                if tag not in self["s:" + diner].keys():
                    self["s:" + diner][tag] = self["s:" + food][tag]
                    continue
                for other_building in self["s:" + food][tag]:
                    if other_building.is_empty():
                        continue
                    found = False
                    for this_building in self["s:" + diner][tag]:
                        if this_building.building == other_building.building:
                            found = True
                            this_building += other_building
                            break
                    if not found:
                        self["s:" + diner][tag].append(other_building)
            # Remove the food from data
            self.pop("s:" + food)

    def merge_states(self, merge_dict):
        # Transfers building ownerships
        for state_id in self.keys():
            if state_id == "if":  # dlc buildings
                continue
            for tag in self[state_id].keys():
                if not isinstance(self[state_id][tag], list):
                    continue
                for building in self[state_id][tag]:
                    if building.is_empty() or building.isMonument:
                        continue
                    for ownership in building.building_ownership:
                        region = ownership["region"].replace(
                            '"', ""
                        )  # Remove '\"' from ownership["region"]
                        for diner, food_list in merge_dict.items():
                            if region in food_list:
                                ownership["region"] = '"' + diner + '"'
                                building.refresh()
                                break
        # Merge building
        for diner, food_list in merge_dict.items():
            for food in food_list:
                self.merge_state(diner, food)
        self.format()

    def get_str(self, state_id):
        if state_id == "if":
            building_tree = Tree(self[state_id])
            return building_tree.__str__()
        building_str = f"    {state_id} = {{\n"
        for tag in self[state_id].keys():
            building_str += f"        {tag} = {{\n"
            for building in self[state_id][tag]:
                building_str += str(building)
            building_str += f"        }}\n"
        building_str += f"    }}\n"

        return building_str

    def __str__(self) -> str:
        building_str = "BUILDINGS = {\n"
        for state_id in self.keys():
            print("Exporting building data: " + state_id)
            building_str += self.get_str(state_id)
        building_str += "}\n"
        return building_str

    def dump(self, dir):
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write("BUILDINGS = {\n")
            for state_id in self.keys():
                print("Exporting building data: " + state_id)
                file.write(self.get_str(state_id))
            file.write("}\n")
