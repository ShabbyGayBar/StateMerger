"""State data parser and merger for Victoria 3.

Handles reading, normalizing, merging, and serializing the game's ``STATES``
block, which defines the initial political geography of the map (country
ownership, provinces, homelands, and claims).

The on-disk format parsed by **pyradox** uses heterogeneous container types
(tuples vs. lists vs. scalars) depending on how many elements a collection
contains.  The :class:`States` class normalizes everything to plain Python
lists so that merge logic can safely append without type-checking everywhere.
"""

from pyradox import Tree


class States(dict):
    """A dict subclass representing the Victoria 3 ``STATES`` block.

    Keys are state identifiers in the form ``"s:STATE_NAME"``.  Each value is
    a dict with the following structure (after :meth:`format` normalization):

    .. code-block:: python

        {
            "create_state": [
                {
                    "country": "c:USA",
                    "owned_provinces": ["x665A3B", ...],
                    "state_type": ["seceded", ...],   # optional
                },
                ...
            ],
            "add_homeland": ["cul_pennsylvanian", ...],  # optional
            "add_claim": ["c:USA", ...],                 # optional
        }

    Parameters
    ----------
    source : dict | Tree | None
        Raw game data.  A :class:`pyradox.Tree` (from parsing a ``.txt``
        file), a plain dict (with a top-level ``"STATES"`` key), or
        ``None`` to create an empty collection.
    """

    def __init__(self, source: dict | Tree | None = None):
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
        """Normalize all container fields to plain Python lists.

        After pyradox parses a ``.txt`` file, single-element collections are
        returned as bare scalars, multi-element collections as tuples, and
        empty collections as empty lists.  This method converts every
        ``create_state``, ``owned_provinces``, ``state_type``,
        ``add_homeland``, and ``add_claim`` value to a list so that
        downstream merge code can uniformly use ``+=`` / ``.append()``.

        States whose raw value is **not** a dict (e.g. a malformed / empty
        entry) are replaced with a minimal ``{"create_state": []}`` dict so
        they don't cause KeyErrors later.
        """
        for state_id in self.keys():
            print(f"Formatting state data: {state_id}")
            # Guard against malformed entries that aren't dicts
            if not isinstance(self[state_id], dict):
                self[state_id] = {"create_state": []}
                continue
            # Normalize create_state to a list of state dicts
            if isinstance(self[state_id]["create_state"], tuple):
                self[state_id]["create_state"] = list(self[state_id]["create_state"])
            elif not isinstance(self[state_id]["create_state"], list):
                self[state_id]["create_state"] = [self[state_id]["create_state"]]
            # Normalize owned_provinces and state_type inside each create_state entry
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
            # Normalize top-level add_homeland cultures
            if "add_homeland" in self[state_id].keys():
                if isinstance(self[state_id]["add_homeland"], tuple):
                    self[state_id]["add_homeland"] = list(
                        self[state_id]["add_homeland"]
                    )
                elif not isinstance(self[state_id]["add_homeland"], list):
                    self[state_id]["add_homeland"] = [self[state_id]["add_homeland"]]
            # Normalize top-level add_claim countries
            if "add_claim" in self[state_id].keys():
                if isinstance(self[state_id]["add_claim"], tuple):
                    self[state_id]["add_claim"] = list(self[state_id]["add_claim"])
                elif not isinstance(self[state_id]["add_claim"], list):
                    self[state_id]["add_claim"] = [self[state_id]["add_claim"]]

    def merge_state(self, this: str, other: str):
        """Merge the *other* state into the *this* state, in-place.

        Parameters
        ----------
        this : str
            The **surviving** state ID (e.g. ``"s:STATE_A"``) that will
            absorb the other state's data.
        other : str
            The **consumed** state ID (e.g. ``"s:STATE_B"``) whose data
            will be merged into *this*.  The caller is responsible for
            removing the *other* key from the dict afterwards.

        Merge rules
        -----------
        **create_state (country ownership):**
            If both states have a ``create_state`` entry for the same country,
            the owned provinces are concatenated.  Otherwise the entire
            ``create_state`` entry from *other* is appended as a new block.

        **add_homeland (cultures):**
            Cultures from *other* are appended to *this* if not already
            present (deduplicated).

        **add_claim (countries):**
            Claims from *other* are appended to *this* if not already
            present.  If *this* has no claims at all, the entire list is
            copied from *other*.
        """
        # Merge create_state entries (country ownership + provinces)
        for province in self[other]["create_state"]:
            for province_ref in self[this]["create_state"]:
                if province["country"] == province_ref["country"]:
                    # Same country — combine owned provinces
                    province_ref["owned_provinces"] += province["owned_provinces"]
                    break
            else:
                # Different country — add as a new create_state block
                self[this]["create_state"].append(province)
        # Merge add_homeland (deduplicate cultures)
        if "add_homeland" in self[other].keys():
            for culture in self[other]["add_homeland"]:
                if culture not in self[this]["add_homeland"]:
                    self[this]["add_homeland"].append(culture)
        # Merge add_claim (deduplicate countries)
        if "add_claim" not in self[this].keys():
            if "add_claim" in self[other].keys():
                self[this]["add_claim"] = self[other]["add_claim"]
        elif "add_claim" in self[other].keys():
            for country in self[other]["add_claim"]:
                if country not in self[this]["add_claim"]:
                    self[this]["add_claim"].append(country)

    def get_str(self, state_id: str) -> str:
        """Serialize a single state back to Victoria 3 ``.txt`` format.

        Parameters
        ----------
        state_id : str
            The state key (e.g. ``"s:STATE_A"``).

        Returns
        -------
        str
            A formatted block indented to nest inside the ``STATES = { … }``
            wrapper (4 spaces for the state block, 8 for inner fields).
        """
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

    def merge_states(self, merge_dict: dict):
        """Apply a merge plan to the entire state collection.

        Parameters
        ----------
        merge_dict : dict
            A mapping of ``{survivor: [consumed, ...]}``.  Each key is a
            state name (without the ``"s:"`` prefix) that will survive;
            each value is a list of state names to be absorbed and removed.

        The method iterates over every diner/food pair, calls
        :meth:`merge_state` to combine the data, then pops the consumed
        state from the dict.  If a consumed state is not present in the
        current data (e.g. it was already removed by a prior merge), it
        is silently skipped.
        """
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:" + food) in self.keys():
                    print(f"Merging {food} state data into {diner}")
                    self.merge_state(("s:" + diner), ("s:" + food))
                    self.pop("s:" + food)

    def __str__(self) -> str:
        """Serialize the full ``STATES`` block to Victoria 3 ``.txt`` format.

        Returns
        -------
        str
            The complete ``STATES = { … }`` block ready to be written to a
            game data file.
        """
        states_str = "STATES = {\n"
        for state_id in self.keys():
            states_str += self.get_str(state_id)
        states_str += "}\n"
        return states_str

    def dump(self, dir):
        """Write the serialized ``STATES`` block to a file.

        Parameters
        ----------
        dir : str
            Output file path.  The file is written with UTF-8 BOM encoding
            (``utf-8-sig``) as required by Victoria 3.
        """
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
