from pyradox import Tree


class Pops(dict):
    def __init__(self, source=None):
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
        for state_id in self.keys():  # Restore the original structure of certain pop keys
            print(f"Formatting pop data: {state_id}")
            for tag in self[state_id].keys():
                if not isinstance(self[state_id][tag], dict):
                    self[state_id][tag] = {"create_pop": []}
                    continue
                if isinstance(self[state_id][tag]["create_pop"], tuple):
                    self[state_id][tag]["create_pop"] = list(
                        self[state_id][tag]["create_pop"]
                    )
                elif not isinstance(self[state_id][tag]["create_pop"], list):
                    self[state_id][tag]["create_pop"] = [
                        self[state_id][tag]["create_pop"]
                    ]

    def merge_state(self, this, other):  # this, other are "state_id" strings
        for tag in self[other].keys():
            if tag in self[this].keys():
                for other_pop in self[other][tag]["create_pop"]:
                    found = False
                    hasAttributeType = "pop_type" in other_pop
                    hasAttributeReligion = "religion" in other_pop
                    for this_pop in self[this][tag]["create_pop"]:
                        if other_pop["culture"] != this_pop["culture"]:
                            continue
                        if hasAttributeType and "pop_type" in this_pop:
                            if other_pop["pop_type"] == this_pop["pop_type"]:
                                if hasAttributeReligion and "religion" in this_pop:
                                    if other_pop["religion"] == this_pop["religion"]:
                                        this_pop["size"] = int(this_pop["size"]) + int(
                                            other_pop["size"]
                                        )
                                        found = True
                                        break
                                elif (
                                    not hasAttributeReligion
                                    and "religion" not in this_pop
                                ):
                                    this_pop["size"] = int(this_pop["size"]) + int(
                                        other_pop["size"]
                                    )
                                    found = True
                                    break
                            continue
                        elif not hasAttributeType and "pop_type" not in this_pop:
                            if hasAttributeReligion and "religion" in this_pop:
                                if other_pop["religion"] == this_pop["religion"]:
                                    this_pop["size"] = int(this_pop["size"]) + int(
                                        other_pop["size"]
                                    )
                                    found = True
                                    break
                            elif (
                                not hasAttributeReligion and "religion" not in this_pop
                            ):
                                this_pop["size"] = int(this_pop["size"]) + int(
                                    other_pop["size"]
                                )
                                found = True
                                break
                    if not found:
                        self[this][tag]["create_pop"].append(other_pop)
            else:
                self[this][tag] = self[other][tag]

    def get_str(self, state_id):
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

    def merge_states(self, merge_dict):
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
