# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""State data parser and merger for Victoria 3.

Handles reading, normalizing, merging, and serializing the game's ``STATES``
block, which defines the initial political geography of the map (country
ownership, provinces, homelands, claims, and initialization scripts).

The on-disk format parsed by **pyradox** uses heterogeneous container types
(tuples vs. lists vs. scalars) depending on how many elements a collection
contains.  The :class:`States` class normalizes everything to plain Python
lists for the modeled fields. Additional state-level clauses retain their
ordered parser trees, including repeated effects and nested script operators.
"""

import logging
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from pyradox import Tree
from pyradox.token import primitive_type_of

logger = logging.getLogger(__name__)

_MODELED_CLAUSES = ("create_state", "add_homeland", "add_claim")


@dataclass(frozen=True)
class _ScriptLiteral:
    """A preformatted scalar for the parser's tree writer."""

    text: str

    def __str__(self) -> str:
        return self.text


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

    Additional clauses are captured at construction and serialized after the
    modeled fields. Merges append their scripts in survivor/donor order without
    deduplication, conflict resolution, or reference rewriting. Dictionary
    inputs use list/tuple values for repeated assignments at every nesting level;
    use a Tree to retain original list syntax, operators, and clause ordering.
    """

    def __init__(self, source: dict | Tree | None = None):
        super().__init__()
        self._script_clauses: dict[str, Tree] = {}
        if source is None:
            return
        if isinstance(source, Tree):
            self._capture_script_clauses(source["STATES"])
            states_dict = source.to_python()
        elif isinstance(source, dict):
            self._capture_script_clauses(source["STATES"])
            states_dict = deepcopy(source)
        else:
            raise TypeError(
                "States can only be initialized with a Tree object, a dict, or None"
            )
        self.update(states_dict["STATES"])
        self.format()

    @staticmethod
    def _script_tree(clauses: dict) -> Tree:
        """Convert dictionary scripts, interpreting sequences as repeated keys."""
        result = Tree()
        for key, values in clauses.items():
            if not isinstance(values, (list, tuple)):
                values = [values]
            for value in values:
                if isinstance(value, dict):
                    value = States._script_tree(value)
                result.append(key, deepcopy(value))
        return result

    def _capture_script_clauses(self, states):
        """Copy unmodeled clauses before conversion loses order and operators."""
        for state_id, state in states.items():
            if isinstance(state, Tree):
                clauses = Tree(state)
                for key in _MODELED_CLAUSES:
                    while key in clauses:
                        del clauses[key]
            elif isinstance(state, dict):
                clauses = self._script_tree(
                    {k: v for k, v in state.items() if k not in _MODELED_CLAUSES}
                )
            else:
                continue
            self._script_clauses[state_id] = clauses

    def _merge_script_clauses(self, this: str, other: str):
        """Append independent donor scripts, retaining repeats and conflicts."""
        target = self._script_clauses.setdefault(this, Tree())
        target += self._script_clauses.get(other, Tree())
        self[this].update(target.to_python())

    def _serialize_script_clauses(self, state_id: str) -> str:
        """Render the captured scripts inside a state block."""
        clauses = Tree(self._script_clauses.get(state_id))
        self._protect_script_literals(clauses)
        return clauses.prettyprint(level=2)

    @staticmethod
    def _protect_script_literals(clauses: Tree):
        """Avoid the upstream writer's string coercion and float rounding.

        Tree has no public indexed value setter. Touch its items only on the
        serialization copy, retaining all grouping/operator/comment metadata.
        """
        for item in clauses._data:
            value = item.value
            if isinstance(value, Tree):
                States._protect_script_literals(value)
            elif isinstance(value, str) and primitive_type_of(value) not in (
                None,
                "str",
            ):
                item.value = _ScriptLiteral(f'"{value}"')
            elif isinstance(value, float):
                item.value = _ScriptLiteral(format(Decimal(str(value)), "f"))

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
            logger.debug("Formatting state data: %s", state_id)
            # Guard against malformed entries that aren't dicts
            if not isinstance(self[state_id], dict):
                self[state_id] = {"create_state": []}
                continue
            # Normalize create_state to a list of state dicts
            self[state_id].setdefault("create_state", [])
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
                if "state_type" in state:
                    if isinstance(state["state_type"], tuple):
                        state["state_type"] = list(state["state_type"])
                    elif not isinstance(state["state_type"], list):
                        state["state_type"] = [state["state_type"]]
            # Normalize top-level add_homeland cultures
            if "add_homeland" in self[state_id]:
                if isinstance(self[state_id]["add_homeland"], tuple):
                    self[state_id]["add_homeland"] = list(
                        self[state_id]["add_homeland"]
                    )
                elif not isinstance(self[state_id]["add_homeland"], list):
                    self[state_id]["add_homeland"] = [self[state_id]["add_homeland"]]
            # Normalize top-level add_claim countries
            if "add_claim" in self[state_id]:
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

        **Additional clauses:**
            Append *other*'s scripts after *this*'s scripts, preserving their
            order and duplicates. Later variable assignments may overwrite
            earlier ones when the game executes the resulting script.
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
        if "add_homeland" in self[other]:
            for culture in self[other]["add_homeland"]:
                if culture not in self[this]["add_homeland"]:
                    self[this]["add_homeland"].append(culture)
        # Merge add_claim (deduplicate countries)
        if "add_claim" not in self[this]:
            if "add_claim" in self[other]:
                self[this]["add_claim"] = self[other]["add_claim"]
        elif "add_claim" in self[other]:
            for country in self[other]["add_claim"]:
                if country not in self[this]["add_claim"]:
                    self[this]["add_claim"].append(country)
        self._merge_script_clauses(this, other)

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
            state_str += "        create_state = {\n"
            state_str += f"            country = {province['country']}\n"
            state_str += "            owned_provinces = { "
            for owned_province in province["owned_provinces"]:
                state_str += f"{owned_province} "
            state_str += "}\n"
            if "state_type" in province:
                for state_type in province["state_type"]:
                    state_str += f"            state_type = {state_type}\n"
            state_str += "        }\n\n"
        if "add_homeland" in self[state_id]:
            for culture in self[state_id]["add_homeland"]:
                state_str += f"        add_homeland = {culture}\n"
        if "add_claim" in self[state_id]:
            for country in self[state_id]["add_claim"]:
                state_str += f"        add_claim = {country}\n"
        state_str += self._serialize_script_clauses(state_id)
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
                    logger.debug("Merging %s state data into %s", food, diner)
                    self.merge_state(("s:" + diner), ("s:" + food))
                    self.pop("s:" + food)
                    self._script_clauses.pop("s:" + food, None)

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

    def dump(self, output_path):
        """Write the serialized ``STATES`` block to a file.

        Parameters
        ----------
        output_path : str
            Output file path.  The file is written with UTF-8 BOM encoding
            (``utf-8-sig``) as required by Victoria 3.
        """
        with open(output_path, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
