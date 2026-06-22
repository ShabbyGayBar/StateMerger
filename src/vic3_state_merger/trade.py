"""Trade route data handling for Victoria 3 state merging.

This module provides the :class:`Trade` class, which parses, formats,
merges, and serialises Vic3 trade-route data (``TRADE`` blocks found
in ``common/goods/`` save-game / mod files).

Data structure
--------------
The internal dict stored by :class:`Trade` follows this hierarchy::

    state_id (str, e.g. "s:STATE_123")
      └─ region_state (str, e.g. "REGION_STATE_456")
           └─ trade_good (str, e.g. "grain")
                ├─ "add_exports" (int) – export volume for the good
                └─ "add_imports" (int) – import volume for the good

When states are merged the *diner* (surviving state) accumulates the
export/import volumes of every *food* (consumed state) so that the
merged state retains the total trade throughput.
"""

from pyradox import Tree


class Trade(dict):
    """A dict subclass that holds and manipulates Vic3 trade-route data.

    Each key is a **state id** string (e.g. ``"s:STATE_123"``); each
    value is a nested dict of region states → trade goods →
    ``{add_exports, add_imports}``.

    Parameters
    ----------
    source : dict | Tree | None
        Raw trade data source.  Accepted types:

        * :class:`~pyradox.Tree` – parsed from a Vic3 ``.txt`` file
          (must contain a top-level ``TRADE`` key).
        * ``dict`` – already-deserialised Python dict with a ``"TRADE"``
          key.
        * ``None`` – creates an empty :class:`Trade` instance.

    Raises
    ------
    TypeError
        If *source* is neither a :class:`~pyradox.Tree`, a ``dict``,
        nor ``None``.
    """

    def __init__(self, source: dict | Tree | None = None):
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
        """Normalise raw trade data into a consistent nested-dict structure.

        After parsing, trade data can arrive in inconsistent forms:

        * A state's value may be a **list** of dicts (each produced by a
          separate ``.txt`` file) rather than a single merged dict.
        * ``add_exports`` / ``add_imports`` values may be strings instead
          of integers (e.g. when parsed from text).

        This method resolves both issues in-place:

        1. **List flattening** – if a state's value is a list, all
           entries are merged into one dict, combining trade-good data
           that appears in multiple list elements.
        2. **Type coercion** – ``add_exports`` and ``add_imports`` are
           converted to ``int`` where possible, defaulting to ``0`` on
           failure.
        """
        for state_id in self.keys():
            print(f"Formatting trade data: {state_id}")

            # --- Flatten list-valued states --------------------------------
            # When multiple .txt files contribute to the same state the
            # parser produces a list of dicts instead of a single dict.
            if isinstance(self[state_id], list):
                merge_dict: dict = {}
                for entry in self[state_id]:
                    for region_state, trade_goods in entry.items():
                        if region_state not in merge_dict:
                            merge_dict[region_state] = {}
                        for trade_good, good_data in trade_goods.items():
                            if trade_good not in merge_dict[region_state]:
                                merge_dict[region_state][trade_good] = good_data
                            else:
                                # Same trade good seen in another list
                                # element – merge its data in.
                                merge_dict[region_state][trade_good].update(good_data)
                self[state_id] = merge_dict

            # --- Coerce numeric fields to int ------------------------------
            for region_state in self[state_id].keys():
                if not isinstance(self[state_id][region_state], dict):
                    continue

                for trade_good in self[state_id][region_state].keys():
                    if isinstance(self[state_id][region_state][trade_good], dict):
                        good_data = self[state_id][region_state][trade_good]

                        # Ensure add_exports is an integer
                        if "add_exports" in good_data and not isinstance(
                            good_data["add_exports"], (int, float)
                        ):
                            try:
                                good_data["add_exports"] = int(good_data["add_exports"])
                            except (ValueError, TypeError):
                                good_data["add_exports"] = 0

                        # Ensure add_imports is an integer
                        if "add_imports" in good_data and not isinstance(
                            good_data["add_imports"], (int, float)
                        ):
                            try:
                                good_data["add_imports"] = int(good_data["add_imports"])
                            except (ValueError, TypeError):
                                good_data["add_imports"] = 0

    def merge_state(self, this: str, other: str):
        """Merge trade data from the *other* state into the *this* state.

        For every ``(region_state, trade_good)`` pair present in
        *other*, the corresponding ``add_exports`` / ``add_imports``
        values are **summed** into *this*.  If a trade good or region
        state does not yet exist in *this*, it is copied from *other*.

        Parameters
        ----------
        this : str
            The **surviving** state id (e.g. ``"s:STATE_1"``).  Receives
            the merged trade data.
        other : str
            The **consumed** state id (e.g. ``"s:STATE_2"``).  Its data
            is merged into *this*.

        Notes
        -----
        The *other* entry is **not** removed from the dict by this
        method.  The caller (see :meth:`merge_states`) is responsible
        for removing it afterwards.
        """
        if other not in self:
            return

        if this not in self:
            self[this] = {}

        for region_state in self[other].keys():
            if region_state not in self[this]:
                self[this][region_state] = {}

            for trade_good in self[other][region_state].keys():
                if trade_good not in self[this][region_state]:
                    # Trade good only exists in the consumed state –
                    # copy it wholesale.
                    self[this][region_state][trade_good] = self[other][region_state][
                        trade_good
                    ].copy()
                else:
                    # Both states have the same trade good – sum their
                    # export/import volumes.
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

    def merge_states(self, merge_dict: dict):
        """Apply a full state-merging plan to trade data.

        Iterates over every *diner → food_list* mapping in *merge_dict*
        and merges each consumed ("food") state's trade data into the
        surviving ("diner") state, then removes the consumed state from
        the dict.

        Parameters
        ----------
        merge_dict : dict
            A mapping of ``{diner: [food, ...]}`` where each key is a
            state that survives the merge and each value is a list of
            states to be consumed.  State ids in this dict **do not**
            include the ``"s:"`` prefix; it is added internally.
        """
        for diner, food_list in merge_dict.items():
            for food in food_list:
                food_key = f"s:{food}"
                diner_key = f"s:{diner}"

                if food_key in self:
                    print(f"Merging {food} trade data into {diner}")
                    self.merge_state(diner_key, food_key)
                    self.pop(food_key)

    def get_str(self, state_id: str) -> str:
        """Return the Vic3 script representation of a single state's trade data.

        The output follows the standard Vic3 trade block format::

            s:STATE_1 = {
                REGION_STATE_1 = {
                    grain = {
                        add_exports = 10
                        add_imports = 5
                    }
                }
            }

        Only trade goods with positive ``add_exports`` or
        ``add_imports`` are included in the output.

        Parameters
        ----------
        state_id : str
            The state id to serialise (e.g. ``"s:STATE_1"``).

        Returns
        -------
        str
            A formatted script string for the state, or an empty string
            if the state id is not present in the trade data.
        """
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
        """Return the full Vic3 script representation of all trade data.

        Wraps every state's output (produced by :meth:`get_str`) inside
        a top-level ``TRADE = { … }`` block.  States with no trade data
        are omitted.
        """
        trade_str = "TRADE = {\n"
        for state_id in self.keys():
            if self[state_id]:
                trade_str += self.get_str(state_id)
        trade_str += "}\n"
        return trade_str

    def dump(self, dir):
        """Write the full trade data to a file in Vic3 script format.

        The file is encoded as UTF-8 with BOM (``utf-8-sig``), matching
        the encoding expected by Victoria 3.

        Parameters
        ----------
        dir : str
            Destination file path.
        """
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
