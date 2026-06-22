"""State region data parsing and merging for Victoria 3 state merging.

This module provides the :class:`StateRegionItem` and :class:`StateRegion`
classes used to parse, merge, and serialize Victoria 3 state region data from
``map_data/state_regions/``.  Each state region defines geographic and economic
properties — provinces, impassable areas, arable land, capped resources,
discoverable resources (gold, rubber, oil), and hub assignments (city, port,
farm, mine, wood).

When states are merged, the absorbing (\"diner\") state accumulates provinces,
impassable areas, arable land, capped resources, and discoverable resources
from the absorbed (\"food\") state.  Hub assignments (city, port, etc.) are
inherited from the food state only when the diner state lacks them.  The
``state_trait_<N>_states_integration`` trait is recomputed to reflect the new
total number of merged states.

The output is written in Vic3 script format with UTF-8 BOM encoding.
"""

from pyradox import Tree

# English word equivalents for the integer suffix in state-trait identifiers.
# Index ``i`` gives the word for ``i`` (e.g. ``seq_str[3] == "three"``),
# used to construct trait names like ``state_trait_three_states_integration``.
seq_str = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]


class StateRegionItem:
    """Represents a single state region from ``map_data/state_regions/``.

    A state region is the fundamental geographic unit in Victoria 3.  It holds
    province lists, economic data (arable land, capped and discoverable
    resources), hub province assignments, and state traits.

    Sea nodes (ocean tiles) are a degenerate form that contain only an ``id``
    and a ``provinces`` list with no economic data.

    Attributes:
        name: The region identifier used as the key in the game data
            (e.g. ``"REGION_GREAT_BRITAIN_1"``).
        id: Numeric state ID used for cross-referencing with other game data.
        subsistence_building: Building type that provides subsistence income
            (e.g. ``"building_subsistence_farms"``).  Empty string for sea nodes.
        provinces: Ordered list of province IDs belonging to this region.
        impassable: List of province IDs that are impassable (mountains, etc.).
        prime_land: List of province IDs designated as prime agricultural land.
        traits: List of state trait identifiers (e.g.
            ``"state_trait_deciduous_forest"``).
        city: Province ID assigned as the region's city hub.
        port: Province ID assigned as the region's port hub (empty if landlocked).
        farm: Province ID assigned as the region's farm hub.
        mine: Province ID assigned as the region's mine hub.
        wood: Province ID assigned as the region's wood hub.
        arable_land: Integer count of arable land slots.
        arable_resources: List of agricultural building types available
            (e.g. ``"bg_plantations"``).
        capped_resources: Mapping of capped resource building types to their
            maximum levels (e.g. ``{"building_iron_mine": 24}``).
        gold: Two-element list ``[undiscovered, discovered]`` gold resource
            amounts.  Gold uses a depletion mechanic: ``building_gold_field``
            depletes into ``building_gold_mine``.
        rubber: Two-element list ``[undiscovered, discovered]`` rubber
            resource amounts.  Rubber can be undiscovered in some states.
        oil: Integer amount of undiscovered oil (``building_oil_rig``).
        naval_exit_id: ID of the sea node that connects to this coastal
            region, or ``-1`` if the region is landlocked.
    """

    def __init__(self, name, dict: dict):
        """Initialize the state region from a parsed game data dictionary.

        The constructor extracts every optional field safely — missing keys
        default to empty collections or sentinel values (``""``, ``-1``).
        Single-value fields that the parser may return as scalars are
        normalised to lists where the game engine expects a list.

        Args:
            name: The region identifier (key) in the source dictionary.
            dict: A dictionary whose sole key is ``name`` and whose value
                contains the region's fields (``id``, ``provinces``,
                ``subsistence_building``, etc.) as parsed by *pyradox*.
        """
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

        # Sea nodes only have id and provinces — skip all economic fields.
        if "subsistence_building" not in dict_data.keys():
            self.subsistence_building = ""
            self.provinces = dict_data["provinces"]
            return

        self.subsistence_building = dict_data["subsistence_building"]
        self.provinces = dict_data["provinces"]

        # Normalise list-or-scalar fields: pyradox may return a single value
        # instead of a list when there is exactly one element, or an empty
        # dict ``{}`` when the block is empty.
        if "impassable" in dict_data.keys():
            if isinstance(dict_data["impassable"], (list, tuple)):
                self.impassable = dict_data["impassable"]
            elif dict_data["impassable"] == {}:
                self.impassable = []
            else:
                self.impassable = [dict_data["impassable"]]
        else:
            self.impassable = []

        if "prime_land" in dict_data.keys():
            if isinstance(dict_data["prime_land"], (list, tuple)):
                self.prime_land = dict_data["prime_land"]
            elif dict_data["prime_land"] == {}:
                self.prime_land = []
            else:
                self.prime_land = [dict_data["prime_land"]]
        else:
            self.prime_land = []

        if "traits" in dict_data.keys():
            if isinstance(dict_data["traits"], (list, tuple)):
                self.traits = dict_data["traits"]
            elif dict_data["traits"] == {}:
                self.traits = []
            else:
                self.traits = [dict_data["traits"]]
        else:
            self.traits = []

        # Hub province assignments — optional per region type.
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

        # arable_resources may be a single value or a list.
        if isinstance(dict_data["arable_resources"], list):
            self.arable_resources = dict_data["arable_resources"]
        else:
            self.arable_resources = [dict_data["arable_resources"]]

        # capped_resources: {building_type: max_level}
        self.capped_resources = {}
        if "capped_resources" in dict_data.keys():
            for resource, amount in dict_data["capped_resources"].items():
                self.capped_resources[resource] = int(amount)

        # Discoverable resources (gold, rubber, oil) live under the
        # ``resource`` key, which may be a single dict or a list of dicts.
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
        """Return the number of original states that have been merged into this region.

        The count is inferred from the presence of a
        ``state_trait_<N>_states_integration`` trait.  If no integration
        trait is present the region represents a single (un-merged) state.

        Returns:
            The merge count as an integer.  Sea nodes return ``0``; an
            un-merged land region returns ``1``.
        """
        if self.is_sea_node():
            return 0
        for i in range(2, 9):
            if f"state_trait_{seq_str[i]}_states_integration" in self.traits:
                return i
        return 1

    def is_sea_node(self):
        """Check whether this region is a sea (ocean) node.

        Sea nodes are identified by the absence of a ``subsistence_building``
        value.

        Returns:
            ``True`` if this is a sea node, ``False`` otherwise.
        """
        if self.subsistence_building == "":
            return True
        return False

    def province_cnt(self):
        """Return the number of provinces in this region.

        Returns:
            Integer count of province IDs in :attr:`provinces`.
        """
        return len(self.provinces)

    def is_small_state(self, limit: int = 4):
        """Check whether this region qualifies as a "small state".

        Small states are land regions whose province count is strictly less
        than *limit*.  They receive special treatment during merging: when
        ``ignoreSmallStates`` is enabled, small states do not increment the
        merge-count trait, preventing artificially inflated integration
        penalties.

        Args:
            limit: Province count threshold (default ``4``).  Regions with
                fewer provinces than this are considered small.

        Returns:
            ``True`` if this is a small state, ``False`` otherwise.
        """
        if self.is_sea_node():
            return False
        if self.province_cnt() < limit:
            return True
        return False

    def merge(self, other, ignoreSmallStates: bool = False, smallStateLimit: int = 4):
        """Merge another :class:`StateRegionItem` into this one.

        The *diner* (``self``) absorbs all data from the *food* (``other``):
        - **Additive fields** (provinces, impassable, prime_land, arable_land,
          capped_resources, gold, rubber, oil) are summed.
        - **Set-like fields** (arable_resources, traits) are unioned —
          duplicates are dropped.
        - **Fallback fields** (city, port, farm, mine, wood, naval_exit_id)
          are taken from *other* only when *self* has no value.
        - The ``state_trait_<N>_states_integration`` trait is recomputed
          to reflect the new total.

        After merging, the food state's data is cleared to prevent
        double-counting if it is still referenced elsewhere.

        Args:
            other: The :class:`StateRegionItem` to absorb into this one.
            ignoreSmallStates: If ``True``, small states (those with fewer
                than *smallStateLimit* provinces) do not contribute to the
                merge-count trait.  This prevents integration penalties for
                absorbing tiny states.
            smallStateLimit: Province count below which a state is considered
                "small" (default ``4``).

        Raises:
            Prints an error message if either region is a sea node — sea
            nodes cannot be merged.
        """
        if self.is_sea_node() or other.is_sea_node():
            print(f"Error: Cannot merge sea node with other state")
            return

        # Additive list fields: simply concatenate.
        self.provinces += other.provinces
        self.impassable += other.impassable
        self.prime_land += other.prime_land

        # Traits: remove the old integration trait from self, copy unique
        # traits from other, then compute and add the new integration trait.
        thisMergeStatesCnt = self.merge_states_cnt()
        otherMergeStatesCnt = other.merge_states_cnt()
        if thisMergeStatesCnt > 1:
            self.traits.remove(
                f"state_trait_{seq_str[thisMergeStatesCnt]}_states_integration"
            )
        for trait in other.traits:
            if (
                trait
                != f"state_trait_{seq_str[otherMergeStatesCnt]}_states_integration"
                and trait not in self.traits
            ):
                self.traits.append(trait)
        totalMergeStatesCnt = thisMergeStatesCnt + otherMergeStatesCnt

        # Optionally exclude small states from the merge count.
        if ignoreSmallStates:
            if self.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
            if other.is_small_state(limit=smallStateLimit):
                totalMergeStatesCnt -= 1
        if (totalMergeStatesCnt > 1) and (totalMergeStatesCnt < 8):
            self.traits.append(
                f"state_trait_{seq_str[totalMergeStatesCnt]}_states_integration"
            )
        elif totalMergeStatesCnt >= 8:
            self.traits.append("state_trait_eight_states_integration")

        # Additive numeric fields.
        self.arable_land += other.arable_land

        # Set-union for arable_resources (avoid duplicates).
        for resource in other.arable_resources:
            if resource not in self.arable_resources:
                self.arable_resources.append(resource)

        # Capped resources: sum levels for shared keys, add new keys.
        for resource, amount in other.capped_resources.items():
            if resource in self.capped_resources.keys():
                self.capped_resources[resource] += int(amount)
            else:
                self.capped_resources[resource] = int(amount)

        # Discoverable resources: sum undiscovered and discovered amounts.
        self.gold[0] += other.gold[0]
        self.gold[1] += other.gold[1]
        self.rubber[0] += other.rubber[0]
        self.rubber[1] += other.rubber[1]
        self.oil += other.oil

        # Fallback fields: inherit from other only when self has no value.
        if self.city == "":
            self.city = other.city
        if self.port == "":
            self.port = other.port
        if self.farm == "":
            self.farm = other.farm
        if self.mine == "":
            self.mine = other.mine
        if self.wood == "":
            self.wood = other.wood
        if self.naval_exit_id == -1:
            self.naval_exit_id = other.naval_exit_id

        # Clear the food state's data to prevent double-counting.
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
        """Export the state region to a Vic3 script-format string.

        The output follows the game's ``.txt`` syntax.  Empty or default-valued
        optional fields are omitted.  Sea nodes produce a minimal block with
        only ``id`` and ``provinces``.

        Returns:
            A string representation of the state region in Vic3 script format,
            terminated by a blank line for readability.
        """
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
        # Discoverable resource blocks — only written when amounts are non-zero.
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
        """Export the state region to a plain Python dictionary.

        The dictionary structure mirrors the game's script format and can be
        re-constructed into a :class:`StateRegionItem` via the constructor.
        Empty or default-valued optional fields are omitted.

        Returns:
            A dictionary representation of the state region.
        """
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

        # Reconstruct discoverable resource entries.
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
    """Ordered dictionary of :class:`StateRegionItem` objects keyed by region name.

    Acts as a thin wrapper around ``dict`` that supports initialisation from
    a *pyradox* :class:`~pyradox.Tree` or a plain Python ``dict``, and
    provides batch-merge and serialisation helpers.

    Example::

        from pyradox import Tree
        tree = Tree.from_file("map_data/state_regions/01_west_europe.txt")
        regions = StateRegion(tree)
        regions.merge_states(merge_dict, ignoreSmallStates=True)
        regions.dump("output/state_regions.txt")
    """

    def __init__(self, source: dict | Tree | None = None):
        """Initialize the state region collection from a data source.

        Args:
            source: One of:

                - ``None`` — creates an empty collection.
                - :class:`pyradox.Tree` — parses the tree into a Python dict
                  and constructs a :class:`StateRegionItem` for each key.
                - ``dict`` — constructs a :class:`StateRegionItem` for each
                  key directly.

        Raises:
            TypeError: If *source* is not ``None``, ``dict``, or
                :class:`pyradox.Tree`.
        """
        if source is None:
            super().__init__()
        elif isinstance(source, Tree):
            source_dict = source.to_python()
            for state_id in source_dict.keys():
                self[state_id] = StateRegionItem(state_id, source_dict)
        elif isinstance(source, dict):
            for state_id in source.keys():
                self[state_id] = StateRegionItem(state_id, source)
        else:
            raise TypeError(
                "StateRegion can only be initialized with a Tree object, a dict, or None"
            )

    def merge_state(
        self, diner, food, ignoreSmallStates: bool = False, smallStateLimit: int = 4
    ):
        """Merge a single food state region into a diner state region.

        After the merge, the food entry is removed from the collection.

        Args:
            diner: Key of the absorbing state region (kept in the collection).
            food: Key of the absorbed state region (removed after merging).
            ignoreSmallStates: Forwarded to :meth:`StateRegionItem.merge`.
            smallStateLimit: Forwarded to :meth:`StateRegionItem.merge`.
        """
        self[diner].merge(
            self[food],
            ignoreSmallStates=ignoreSmallStates,
            smallStateLimit=smallStateLimit,
        )
        self.pop(food)

    def merge_states(
        self,
        merge_dict: dict,
        ignoreSmallStates: bool = False,
        smallStateLimit: int = 4,
    ) -> dict[int, list[int]]:
        """Merge multiple state regions according to a merge plan.

        Iterates over *merge_dict*, merging each food state list into the
        corresponding diner.  The merge order within each food list follows
        the list's iteration order.

        Args:
            merge_dict: Mapping of ``diner_key -> [food_key, ...]`` describing
                which state regions to absorb and into which surviving region.
            ignoreSmallStates: Forwarded to :meth:`merge_state`.
            smallStateLimit: Forwarded to :meth:`merge_state`.

        Returns:
            A mapping of ``diner_id -> [food_id, ...]`` using the **numeric**
            state IDs (rather than the string keys), suitable for passing to
            other data-layer merge functions (buildings, pops, etc.) that
            identify states by ID.
        """
        id_dict = {}
        for diner, food_list in merge_dict.items():
            id_dict[int(self[diner].id)] = []
            for food in food_list:
                id_dict[int(self[diner].id)].append(int(self[food].id))
                self.merge_state(
                    diner,
                    food,
                    ignoreSmallStates=ignoreSmallStates,
                    smallStateLimit=smallStateLimit,
                )
        return id_dict

    def __str__(self, include_sea_nodes: bool = False):
        """Export all state regions to a single Vic3 script-format string.

        Args:
            include_sea_nodes: If ``True``, sea nodes are included in the
                output.  Default ``False`` omits them.

        Returns:
            Concatenated script-format string of all (non-sea) state regions.
        """
        state_str = ""
        for state_region_item in self.values():
            if not include_sea_nodes and state_region_item.is_sea_node():
                continue
            state_str += str(state_region_item)
        return state_str

    def dump(self, dir, include_sea_nodes: bool = False):
        """Write all state regions to a file in Vic3 script format.

        The file is written with UTF-8 BOM encoding (``utf-8-sig``), matching
        the game's expected encoding.

        Args:
            dir: Output file path.
            include_sea_nodes: If ``True``, sea nodes are included.
        """
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(self.__str__(include_sea_nodes=include_sea_nodes))

    def provinces_count_dict(self):
        """Return a mapping of region keys to their province counts.

        Returns:
            Dictionary ``{region_name: province_count}`` for every region
            (including sea nodes).
        """
        count_dict = {}
        for state_id, state in self.items():
            count_dict[state_id] = state.province_cnt()
        return count_dict

    def to_python(self):
        """Export the entire collection to a nested Python dictionary.

        Returns:
            Dictionary ``{region_name: region_dict}`` where each
            ``region_dict`` is the output of
            :meth:`StateRegionItem.to_python`.
        """
        state_region_dict = {}
        for state_id, state in self.items():
            state_region_dict[state_id] = state.to_python()
        return state_region_dict
