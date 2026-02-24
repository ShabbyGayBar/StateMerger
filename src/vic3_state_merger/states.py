from pyradox import Tree


class States(dict):
    def __init__(self, source:dict|Tree|None=None):
        super().__init__()
        if source is None:
            return
        if isinstance(source, Tree):
            states_dict = source.to_python()
        elif isinstance(source, dict):
            states_dict = source
        else:
            raise TypeError(
                "States can only be initialized with a Tree object, a dict, or None"
            )
        self.update(states_dict["STATES"])
        self.format()

    def format(self):
        for state_id in self.keys():
            print(f"Formatting state data: {state_id}")
            if not isinstance(self[state_id], dict):
                self[state_id] = {"create_state": []}
                continue
            if isinstance(self[state_id]["create_state"], tuple):
                self[state_id]["create_state"] = list(self[state_id]["create_state"])
            elif not isinstance(self[state_id]["create_state"], list):
                self[state_id]["create_state"] = [self[state_id]["create_state"]]
            for state in self[state_id]["create_state"]:
                if isinstance(state["owned_provinces"], tuple):
                    state["owned_provinces"] = list(state["owned_provinces"])
                elif not isinstance(state["owned_provinces"], list):
                    state["owned_provinces"] = [state["owned_provinces"]]
                if "state_type" in state.keys():
                    if isinstance(state["state_type"], tuple):
                        state["state_type"] = list(state["state_type"])
                    elif not isinstance(state["state_type"], list):
                        state["state_type"] = [state["state_type"]]
            if "add_homeland" in self[state_id].keys():
                if isinstance(self[state_id]["add_homeland"], tuple):
                    self[state_id]["add_homeland"] = list(
                        self[state_id]["add_homeland"]
                    )
                elif not isinstance(self[state_id]["add_homeland"], list):
                    self[state_id]["add_homeland"] = [self[state_id]["add_homeland"]]
            if "add_claim" in self[state_id].keys():
                if isinstance(self[state_id]["add_claim"], tuple):
                    self[state_id]["add_claim"] = list(self[state_id]["add_claim"])
                elif not isinstance(self[state_id]["add_claim"], list):
                    self[state_id]["add_claim"] = [self[state_id]["add_claim"]]

    def merge_state(self, this:str, other:str):  # this, other are "state_id" strings
        # Merge create_state
        for province in self[other]["create_state"]:
            for province_ref in self[this]["create_state"]:
                if province["country"] == province_ref["country"]:
                    province_ref["owned_provinces"] += province["owned_provinces"]
                    break
            else:
                self[this]["create_state"].append(province)
        # Merge add_homeland
        if "add_homeland" in self[other].keys():
            for culture in self[other]["add_homeland"]:
                if culture not in self[this]["add_homeland"]:
                    self[this]["add_homeland"].append(culture)
        # Merge add_claim
        if "add_claim" not in self[this].keys():
            if "add_claim" in self[other].keys():
                self[this]["add_claim"] = self[other]["add_claim"]
        elif "add_claim" in self[other].keys():
            for country in self[other]["add_claim"]:
                if country not in self[this]["add_claim"]:
                    self[this]["add_claim"].append(country)

    def get_str(self, state_id:str) -> str:
        state_str = f"    {state_id} = {{\n"
        for province in self[state_id]["create_state"]:
            state_str += f"        create_state = {{\n"
            state_str += f'            country = {province["country"]}\n'
            state_str += f"            owned_provinces = {{ "
            for owned_province in province["owned_provinces"]:
                state_str += f"{owned_province} "
            state_str += "}\n"
            if "state_type" in province.keys():
                for state_type in province["state_type"]:
                    state_str += f"            state_type = {state_type}\n"
            state_str += "        }\n\n"
        if "add_homeland" in self[state_id].keys():
            for culture in self[state_id]["add_homeland"]:
                state_str += f"        add_homeland = {culture}\n"
        if "add_claim" in self[state_id].keys():
            for country in self[state_id]["add_claim"]:
                state_str += f"        add_claim = {country}\n"
        state_str += "    }\n"

        return state_str

    def merge_states(self, merge_dict:dict):
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:" + food) in self.keys():
                    print(f"Merging {food} state data into {diner}")
                    self.merge_state(("s:" + diner), ("s:" + food))
                    self.pop("s:" + food)

    def __str__(self) -> str:
        states_str = "STATES = {\n"
        for state_id in self.keys():
            states_str += self.get_str(state_id)
        states_str += "}\n"
        return states_str

    def dump(self, dir):
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
