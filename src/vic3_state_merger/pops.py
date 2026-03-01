from pyradox import Tree


class Pops(dict):
    def __init__(self, source: dict | Tree | None = None):
        super().__init__()
        if source is None:
            return
        if isinstance(source, Tree):
            pops_dict = source.to_python()
        elif isinstance(source, dict):
            pops_dict = source
        else:
            raise TypeError(
                "Pops can only be initialized with a Tree object, a dict, or None"
            )
        self.update(pops_dict["POPS"])
        self.format()

    def format(self):
        # Restore the original structure of certain pop keys
        for state_id in self.keys():
            print(f"Formatting pop data: {state_id}")
            for tag in self[state_id].keys():
                if not isinstance(self[state_id][tag], dict):
                    self[state_id][tag] = {"create_pop": []}
                elif isinstance(self[state_id][tag]["create_pop"], tuple):
                    self[state_id][tag]["create_pop"] = list(
                        self[state_id][tag]["create_pop"]
                    )
                elif not isinstance(self[state_id][tag]["create_pop"], list):
                    self[state_id][tag]["create_pop"] = [
                        self[state_id][tag]["create_pop"]
                    ]

    def merge_state(self, this: str, other: str):  # this, other are "state_id" strings
        for tag in self[other].keys():
            if tag not in self[this].keys():
                self[this][tag] = self[other][tag]
                continue
            for other_pop in self[other][tag]["create_pop"]:
                hasAttributeType = "pop_type" in other_pop
                hasAttributeReligion = "religion" in other_pop
                for this_pop in self[this][tag]["create_pop"]:
                    # if culture does not match, skip
                    if other_pop["culture"] != this_pop["culture"]:
                        continue
                    # if pop_type does not match, skip
                    if hasAttributeType:
                        if "pop_type" not in this_pop:
                            continue
                        if other_pop["pop_type"] != this_pop["pop_type"]:
                            continue
                    else:
                        if "pop_type" in this_pop:
                            continue
                    # if religion does not match, skip
                    if hasAttributeReligion:
                        if "religion" not in this_pop:
                            continue
                        if other_pop["religion"] != this_pop["religion"]:
                            continue
                    else:
                        if "religion" in this_pop:
                            continue
                    # pops match. add the sizes together and break out of the loop
                    this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                    break
                # if the loop completes without finding a match, add the other pop to this state
                else:
                    self[this][tag]["create_pop"].append(other_pop)

    def get_str(self, state_id: str) -> str:
        state_str = f"    {state_id} = {{\n"
        for tag in self[state_id].keys():
            state_str += f"        {tag} = {{\n"
            for pop in self[state_id][tag]["create_pop"]:
                state_str += f"            create_pop = {{\n"
                for key, value in pop.items():
                    state_str += f"                {key} = {value}\n"
                state_str += f"            }}\n"
            state_str += f"        }}\n"
        state_str += f"    }}\n"

        return state_str

    def merge_states(self, merge_dict: dict):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:" + food) in self.keys():
                    print(f"Merging {food} pop data into {diner}")
                    self.merge_state(("s:" + diner), ("s:" + food))
                    self.pop("s:" + food)

    def __str__(self) -> str:
        pops_str = "POPS = {\n"
        for state_id in self.keys():
            # print("Generating pop data string: " + state_id)
            pops_str += self.get_str(state_id)
        pops_str += "}\n"
        return pops_str

    def dump(self, dir):
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
