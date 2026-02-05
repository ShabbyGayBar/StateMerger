from pyradox import Tree


class Trade(dict):

    def __init__(self, source:dict|Tree|None=None):
        super().__init__()
        if source is None:
            return
        if isinstance(source, Tree):
            trade_dict = source.to_python()
        elif isinstance(source, dict):
            trade_dict = source
        else:
            raise TypeError(
                "Trade can only be initialized with a Tree object, a dict, or None"
            )
        self.update(trade_dict["TRADE"])
        self.format()

    def format(self):
        # Format trade data to ensure consistent structure
        for state_id in self.keys():
            print(f"Formatting trade data: {state_id}")
            if isinstance(self[state_id], list):
                merge_dict = {}
                for entry in self[state_id]:
                    for region_state, trade_goods in entry.items():
                        if region_state not in merge_dict:
                            merge_dict[region_state] = {}
                        for trade_good, good_data in trade_goods.items():
                            if trade_good not in merge_dict[region_state]:
                                merge_dict[region_state][trade_good] = good_data
                            else:
                                # Merge trade good data
                                merge_dict[region_state][trade_good].update(good_data)
                self[state_id] = merge_dict

            # Ensure region_state entries are properly formatted
            for region_state in self[state_id].keys():
                if not isinstance(self[state_id][region_state], dict):
                    continue

                # Ensure trade goods are properly formatted
                for trade_good in self[state_id][region_state].keys():
                    if isinstance(self[state_id][region_state][trade_good], dict):
                        # Convert single values to proper structure if needed
                        good_data = self[state_id][region_state][trade_good]
                        if "add_exports" in good_data and not isinstance(
                            good_data["add_exports"], (int, float)
                        ):
                            try:
                                good_data["add_exports"] = int(good_data["add_exports"])
                            except (ValueError, TypeError):
                                good_data["add_exports"] = 0
                        if "add_imports" in good_data and not isinstance(
                            good_data["add_imports"], (int, float)
                        ):
                            try:
                                good_data["add_imports"] = int(good_data["add_imports"])
                            except (ValueError, TypeError):
                                good_data["add_imports"] = 0

    def merge_state(self, this:str, other:str):  # this, other are "state_id" strings
        """Merge trade data from 'other' state into 'this' state"""
        if other not in self:
            return

        if this not in self:
            self[this] = {}

        # Merge each region_state from other into this
        for region_state in self[other].keys():
            if region_state not in self[this]:
                self[this][region_state] = {}

            # Merge trade goods for each region_state
            for trade_good in self[other][region_state].keys():
                if trade_good not in self[this][region_state]:
                    # Copy the entire trade good entry
                    self[this][region_state][trade_good] = self[other][
                        region_state
                    ][trade_good].copy()
                else:
                    # Merge exports and imports
                    other_good = self[other][region_state][trade_good]
                    this_good = self[this][region_state][trade_good]

                    if "add_exports" in other_good:
                        if "add_exports" in this_good:
                            this_good["add_exports"] += other_good["add_exports"]
                        else:
                            this_good["add_exports"] = other_good["add_exports"]

                    if "add_imports" in other_good:
                        if "add_imports" in this_good:
                            this_good["add_imports"] += other_good["add_imports"]
                        else:
                            this_good["add_imports"] = other_good["add_imports"]

    def merge_states(self, merge_dict:dict):
        """Merge trade data according to state merging dictionary"""
        for diner, food_list in merge_dict.items():
            for food in food_list:
                food_key = f"s:{food}"
                diner_key = f"s:{diner}"

                if food_key in self:
                    print(f"Merging {food} trade data into {diner}")
                    self.merge_state(diner_key, food_key)
                    self.pop(food_key)

    def get_str(self, state_id:str) -> str:
        """Generate string representation for a state's trade data"""
        if state_id not in self:
            return ""

        state_str = f"    {state_id}={{\n"

        for region_state, trade_data in self[state_id].items():
            if not trade_data:
                continue

            state_str += f"        {region_state}={{\n"

            for trade_good, good_data in trade_data.items():
                if not good_data:
                    continue

                state_str += f"            {trade_good} = {{\n"

                if "add_exports" in good_data and good_data["add_exports"] > 0:
                    state_str += (
                        f'                add_exports = {good_data["add_exports"]}\n'
                    )

                if "add_imports" in good_data and good_data["add_imports"] > 0:
                    state_str += (
                        f'                add_imports = {good_data["add_imports"]}\n'
                    )

                state_str += f"            }}\n"

            state_str += f"        }}\n"

        state_str += f"    }}\n"
        return state_str

    def __str__(self) -> str:
        trade_str = "TRADE = {\n"
        for state_id in self.keys():
            if self[state_id]:  # Only include states with trade data
                trade_str += self.get_str(state_id)
        trade_str += "}\n"
        return trade_str

    def dump(self, dir):
        """Export trade data to file"""
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
