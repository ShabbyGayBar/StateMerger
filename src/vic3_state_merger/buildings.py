"""Building data parsing and merging for Victoria 3 state merging.

This module provides the :class:`Building` and :class:`Buildings` classes used
to parse, merge, and serialize Victoria 3 building data.  When states are
merged, buildings from the absorbed (\"food\") state are combined into the
absorbing (\"diner\") state: matching building types have their ownership
levels summed, while non-matching buildings are appended.

The output is written in Vic3 script format with UTF-8 BOM encoding.
"""

from pyradox import Tree


class Building:
    """Represents a single ``create_building`` block from a Victoria 3 save or game data file.

    Attributes:
        building: The building type identifier (e.g. ``"bg_manufacturing"``),
            or ``None`` if the block is empty.
        building_ownership: List of ownership dicts with keys
            ``type``, ``country``, ``levels``, ``region``.  Represents
            privately/locally/nationally owned building levels.
        country_ownership: List of ownership dicts with keys
            ``country``, ``levels``.  Represents country-owned levels.
        company_ownership: List of ownership dicts with keys
            ``type``, ``country``, ``levels``.  Represents company-owned levels.
        reserves: Cash reserves stored in the building.
        activate_production_methods: List of production method identifiers
            active on this building.
        isMonument: ``True`` if this building is a monument (detected by the
            presence of a ``level`` key in the source dict).  Monuments have
            no ownership entries.
    """

    def __init__(self, dict: dict):
        """Initialize the building from a parsed ``create_building`` dictionary.

        Args:
            dict: A dictionary parsed from a ``create_building`` block.  Expected
                keys include ``building``, ``add_ownership``, ``reserves``,
                ``activate_production_methods``, and optionally ``level`` (which
                indicates a monument).
        """
        if "building" in dict.keys():
            self.building = dict["building"]
        else:
            self.building = None
        self.building_ownership = []
        self.country_ownership = []
        self.company_ownership = []
        self.reserves = 0
        self.activate_production_methods = []
        # Monuments use "level" instead of ownership entries
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

    def add_ownership(self, ownership_dict: dict):
        """Parse and append ownership entries from an ``add_ownership`` dictionary.

        Each key (``building``, ``country``, ``company``) may map to a single
        ownership dict or a list of ownership dicts.  Both forms are handled.

        Args:
            ownership_dict: A dictionary with optional keys ``building``,
                ``country``, and/or ``company``, each containing ownership
                entry dicts or lists thereof.
        """
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
        """Check whether this building has no meaningful content.

        Returns:
            ``True`` if the building type is ``None``, or if it is a
            non-monument with no ownership entries of any kind.
        """
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
        """Sort and deduplicate building ownership entries.

        Merges ``building_ownership`` entries that share the same ``type``,
        ``country``, and ``region`` by summing their ``levels`` values.
        Entries with unique key combinations are kept as-is.  If the
        building is empty, all ownership lists are cleared and the building
        type is reset to ``None``.

        Also ensures ``activate_production_methods`` is always a list.
        """
        if self.is_empty():
            self.building = None
            self.building_ownership = []
            self.country_ownership = []
            self.company_ownership = []
            return
        # Deduplicate building_ownership: merge entries with matching
        # type + country + region by summing their levels
        sorted_ownership = []
        for other_ownership in self.building_ownership:
            for this_ownership in sorted_ownership:
                if (
                    this_ownership["type"] == other_ownership["type"]
                    and this_ownership["country"] == other_ownership["country"]
                    and this_ownership["region"] == other_ownership["region"]
                ):
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        other_ownership["levels"]
                    )
                    break
            else:
                sorted_ownership.append(other_ownership)
        self.building_ownership = sorted_ownership
        # Ensure activate_production_methods is always a list
        if not isinstance(self.activate_production_methods, list):
            self.activate_production_methods = [self.activate_production_methods]

    def level_cnt(self):
        """Return the total number of building levels across all ownership types.

        For monuments, always returns ``1``.  For regular buildings, sums the
        ``levels`` field from every entry in ``building_ownership``,
        ``country_ownership``, and ``company_ownership``.

        Returns:
            Total level count as an ``int``.
        """
        if self.isMonument:
            return 1
        levels = 0
        for ownership in (
            self.building_ownership + self.country_ownership + self.company_ownership
        ):
            levels += int(ownership["levels"])
        return levels

    def __iadd__(self, other):
        """Merge another :class:`Building` into this one in-place.

        For each ownership category (``building_ownership``,
        ``country_ownership``, ``company_ownership``), entries from *other*
        that match an existing entry's key fields have their ``levels``
        summed into the existing entry.  Non-matching entries are appended.

        - **building_ownership** matches on ``type`` + ``country`` + ``region``.
        - **country_ownership** matches on ``country``.
        - **company_ownership** matches on ``type`` + ``country``.

        Args:
            other: The :class:`Building` to merge into this one.

        Returns:
            self: The merged building.

        Raises:
            ValueError: If the two buildings have different ``building`` types.
        """
        if self.building != other.building:
            raise ValueError("Cannot add buildings with different types")
        # Merge building_ownership: match on type + country + region
        for ownership in other.building_ownership:
            for this_ownership in self.building_ownership:
                if (
                    this_ownership["type"] == ownership["type"]
                    and this_ownership["country"] == ownership["country"]
                    and this_ownership["region"] == ownership["region"]
                ):
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
                    break
            else:
                self.building_ownership.append(ownership)
        # Merge country_ownership: match on country only
        for ownership in other.country_ownership:
            for this_ownership in self.country_ownership:
                if this_ownership["country"] == ownership["country"]:
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
                    break
            else:
                self.country_ownership.append(ownership)
        # Merge company_ownership: match on type + country
        for ownership in other.company_ownership:
            for this_ownership in self.company_ownership:
                if (
                    this_ownership["type"] == ownership["type"]
                    and this_ownership["country"] == ownership["country"]
                ):
                    this_ownership["levels"] = int(this_ownership["levels"]) + int(
                        ownership["levels"]
                    )
                    break
            else:
                self.company_ownership.append(ownership)
        return self

    def __str__(self):
        """Serialize this building to Victoria 3 script format.

        Returns:
            A string containing a ``create_building`` block with all
            ownership entries, reserves, and production methods in the
            game's expected script syntax.
        """
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
    """A dictionary mapping state IDs to their parsed building data.

    Inherits from :class:`dict`.  Keys are state ID strings (prefixed with
    ``s:``, e.g. ``"s:STATE_123"``) or the special key ``"if"`` for DLC
    conditional building blocks.  Each value is a dict of
    ``tag -> [Building]``, where *tag* is a country tag (e.g. ``"USA"``).

    Example structure::

        {
            "s:STATE_123": {
                "USA": [Building(...), Building(...)],
                "FRA": [Building(...)],
            },
            "if": { ... },  # DLC buildings
        }
    """

    def __init__(self, source: dict | Tree | None = None):
        """Initialize the Buildings collection from a data source.

        Args:
            source: The data source to parse.  Can be:

                - ``None``: creates an empty collection.
                - :class:`pyradox.Tree`: parsed from a Vic3 ``.txt`` file.
                  DLC ``if`` blocks are extracted and stored under the
                  ``"if"`` key.
                - ``dict``: a pre-parsed dictionary with a ``BUILDINGS``
                  top-level key.

        Raises:
            TypeError: If *source* is not a ``Tree``, ``dict``, or ``None``.
        """
        super().__init__()
        if source is None:
            return
        elif isinstance(source, Tree):
            buildings_dict = source["BUILDINGS"]
            # Extract DLC conditional blocks before converting to dict
            if isinstance(buildings_dict, Tree):
                for dlc_building in buildings_dict.find_all("if"):
                    if isinstance(dlc_building, Tree):
                        self["if"] = dlc_building.to_python(
                            duplicate_action="overwrite"
                        )
            buildings_dict = source.to_python()
        elif isinstance(source, dict):
            buildings_dict = source
        else:
            raise TypeError(
                "Buildings can only be initialized with a Tree object, a dict, or None"
            )
        for state_id in buildings_dict["BUILDINGS"].keys():
            if state_id == "if":  # dlc buildings
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
                # Normalize single create_building entries to a list
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
        """Remove empty buildings from all states.

        Iterates through every state and tag, removing any :class:`Building`
        entries where :meth:`Building.is_empty` returns ``True``.
        """
        for state_id in self.keys():
            if state_id == "if":
                continue
            for tag in self[state_id].keys():
                # Iterate in reverse to safely remove by index
                for i in range(len(self[state_id][tag]), 0, -1):
                    if self[state_id][tag][i - 1].is_empty():
                        self[state_id][tag].pop(i - 1)

    def merge_state(self, diner: str, food: str):
        """Merge one state's buildings into another.

        For each country tag present in the *food* state:

        - If the tag does not exist in the *diner* state, all buildings are
          transferred directly.
        - If the tag exists, buildings with matching ``building`` types are
          merged via :meth:`Building.__iadd__` (summing ownership levels).
          Non-matching buildings are appended.

        After merging, the *food* state entry is removed from the collection.

        Args:
            diner: The absorbing state ID (without the ``s:`` prefix),
                e.g. ``"STATE_123"``.
            food: The absorbed state ID (without the ``s:`` prefix),
                e.g. ``"STATE_456"``.
        """
        if ("s:" + food) in self.keys():
            for tag in self["s:" + food].keys():
                if tag not in self["s:" + diner].keys():
                    # Transfer all buildings for tags not present in diner
                    self["s:" + diner][tag] = self["s:" + food][tag]
                    continue
                for other_building in self["s:" + food][tag]:
                    if other_building.is_empty():
                        continue
                    # Try to find a matching building type in diner and merge
                    for this_building in self["s:" + diner][tag]:
                        if this_building.building == other_building.building:
                            this_building += other_building
                            break
                    else:
                        # No matching building type found; append as new
                        self["s:" + diner][tag].append(other_building)
            # Remove the food state after merging
            self.pop("s:" + food)

    def merge_states(self, merge_dict: dict):
        """Merge buildings according to a state merge plan.

        This is a two-phase operation:

        1. **Reassign ownership regions**: For every building across all
           states, each ``building_ownership`` entry's ``region`` field is
           checked against the merge plan.  If the region belongs to a
           "food" state, it is updated to point to the "diner" (absorbing)
           state, and the building's ownership is refreshed to re-deduplicate.

        2. **Merge building lists**: For each diner/food pair in the merge
           plan, the food state's buildings are combined into the diner
           state via :meth:`merge_state`.

        Args:
            merge_dict: A dictionary mapping diner state IDs to lists of
                food state IDs, e.g. ``{"STATE_123": ["STATE_456", "STATE_789"]}``.
        """
        # Phase 1: Reassign ownership regions to reflect the merge plan
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
                        # Strip quotes from region for comparison
                        region = ownership["region"].replace('"', "")
                        for diner, food_list in merge_dict.items():
                            if region in food_list:
                                # Reassign region to the diner state
                                ownership["region"] = '"' + diner + '"'
                                building.refresh()
                                break
        # Phase 2: Merge building lists for each diner/food pair
        for diner, food_list in merge_dict.items():
            for food in food_list:
                self.merge_state(diner, food)
        self.format()

    def get_str(self, state_id: str) -> str:
        """Serialize a single state's buildings to Victoria 3 script format.

        For the special ``"if"`` key (DLC buildings), the underlying
        :class:`pyradox.Tree` is pretty-printed.  For regular state IDs,
        each tag and its buildings are written in nested script syntax.

        Args:
            state_id: The state key to serialize (e.g. ``"s:STATE_123"``
                or ``"if"``).

        Returns:
            A script-format string for the requested state.
        """
        if state_id == "if":
            building_tree = Tree({"if": self["if"]})
            return building_tree.prettyprint(level=1)
        building_str = f"    {state_id} = {{\n"
        for tag in self[state_id].keys():
            building_str += f"        {tag} = {{\n"
            for building in self[state_id][tag]:
                building_str += str(building)
            building_str += f"        }}\n"
        building_str += f"    }}\n"

        return building_str

    def __str__(self) -> str:
        """Serialize the entire BUILDINGS tree to Victoria 3 script format.

        Returns:
            A string containing the full ``BUILDINGS = { ... }`` block.
        """
        building_str = "BUILDINGS = {\n"
        for state_id in self.keys():
            print("Exporting building data: " + state_id)
            building_str += self.get_str(state_id)
        building_str += "}\n"
        return building_str

    def dump(self, dir):
        """Write the entire BUILDINGS tree to a file in Victoria 3 script format.

        The output file is written with UTF-8 BOM encoding (``utf-8-sig``),
        as required by Victoria 3.

        Args:
            dir: The output file path to write to.
        """
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write("BUILDINGS = {\n")
            for state_id in self.keys():
                print("Exporting building data: " + state_id)
                file.write(self.get_str(state_id))
            file.write("}\n")
