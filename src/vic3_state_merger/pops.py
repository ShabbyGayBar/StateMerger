"""Population data parsing and merging for Victoria 3 state merging.

This module provides the :class:`Pops` class used to parse, merge, and
serialize Victoria 3 population (``POPS``) data.  When states are merged,
pops from the absorbed (\"food\") state are combined into the absorbing
(\"diner\") state: pops that share the same culture, pop type, and religion
have their sizes summed together, while non-matching pops are appended.

The output is written in Vic3 script format with UTF-8 BOM encoding.

Data structure
--------------
After parsing, the internal dictionary has the form::

    {
        "s:STATE_123": {
            "USA": {"create_pop": [
                {"culture": "american", "religion": "protestant", "pop_type": "laborers", "size": 1000},
                ...
            ]},
            "FRA": {"create_pop": [...]},
        },
        ...
    }

- **Top-level keys** are state IDs prefixed with ``s:`` (e.g. ``"s:STATE_123"``).
- **Second-level keys** are country tags (e.g. ``"USA"``).
- **Values** are dicts with a single ``"create_pop"`` key mapping to a list
  of pop dictionaries, each containing ``culture``, ``size``, and optionally
  ``pop_type`` and ``religion``.
"""

from pyradox import Tree


class Pops(dict):
    """A dictionary mapping state IDs to their parsed population data.

    Inherits from :class:`dict`.  Keys are state ID strings prefixed with
    ``s:`` (e.g. ``"s:STATE_123"``).  Each value is a dict of
    ``tag -> {"create_pop": [pop_dict, ...]}``, where *tag* is a country
    tag (e.g. ``"USA"``) and each *pop_dict* contains ``culture``,
    ``size``, and optionally ``pop_type`` and ``religion``.
    """

    def __init__(self, source: dict | Tree | None = None):
        """Initialize the Pops collection from a data source.

        Args:
            source: The data source to parse.  Can be:

                - ``None``: creates an empty collection.
                - :class:`pyradox.Tree`: parsed from a Vic3 ``.txt`` file.
                - ``dict``: a pre-parsed dictionary with a ``POPS``
                  top-level key.

        Raises:
            TypeError: If *source* is not a ``Tree``, ``dict``, or ``None``.
        """
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
        """Normalize the internal pop data structure after parsing.

        The pyradox parser may produce inconsistent structures for pop
        entries depending on whether a state has a single pop or multiple
        pops under a given country tag.  This method ensures every tag
        value is a dict with a ``"create_pop"`` key pointing to a **list**
        of pop dictionaries.

        Specifically:

        - If a tag value is a list (caused by multiple ``create_pop``
          blocks being merged by the parser), it is restructured into
          ``{"create_pop": [...]}`` by flattening all inner
          ``create_pop`` entries.
        - If a tag value is not a dict at all, it is replaced with an
          empty ``{"create_pop": []}``.
        - If ``create_pop`` is a single dict or tuple, it is wrapped
          in a list so that all ``create_pop`` values are uniformly lists.

        Raises:
            ValueError: If a pop entry inside a list does not contain
                a ``"create_pop"`` key, indicating unexpected data format.
        """
        for state_id in self.keys():
            print(f"Formatting pop data: {state_id}")
            for tag in self[state_id].keys():
                # Case 1: parser merged multiple create_pop blocks into a list
                if isinstance(self[state_id][tag], list):
                    raw_pop_list = self[state_id][tag]
                    self[state_id][tag] = {"create_pop": []}
                    for pop in raw_pop_list:
                        if "create_pop" in pop:
                            self[state_id][tag]["create_pop"].extend(pop["create_pop"])
                        else:
                            raise ValueError(
                                f"Unexpected pop format in state {state_id}, tag {tag}: {pop}"
                            )
                # Case 2: tag value is not a dict (e.g. a bare string) – reset to empty
                if not isinstance(self[state_id][tag], dict):
                    self[state_id][tag] = {"create_pop": []}
                # Case 3: create_pop is a tuple (from pyradox) – convert to list
                elif isinstance(self[state_id][tag]["create_pop"], tuple):
                    self[state_id][tag]["create_pop"] = list(
                        self[state_id][tag]["create_pop"]
                    )
                # Case 4: create_pop is a single dict – wrap in a list
                elif not isinstance(self[state_id][tag]["create_pop"], list):
                    self[state_id][tag]["create_pop"] = [
                        self[state_id][tag]["create_pop"]
                    ]

    def merge_state(self, this: str, other: str):
        """Merge one state's pops into another, combining matching pops by size.

        For each country tag present in the *other* (food) state:

        - If the tag does not exist in *this* (diner) state, all pops are
          transferred directly.
        - If the tag exists, each pop from *other* is compared against every
          pop in *this* with the same tag.  Two pops **match** when all of
          the following are equal:

          1. ``culture`` (required on both pops)
          2. ``pop_type`` – either both have it and it matches, or neither has it
          3. ``religion`` – either both have it and it matches, or neither has it

          Matching pops have their ``size`` values summed.  Non-matching pops
          from *other* are appended to the *this* state's pop list.

        Args:
            this: The absorbing (diner) state ID **with** the ``s:`` prefix
                (e.g. ``"s:STATE_123"``).
            other: The absorbed (food) state ID **with** the ``s:`` prefix
                (e.g. ``"s:STATE_456"``).
        """
        for tag in self[other].keys():
            if tag not in self[this].keys():
                self[this][tag] = self[other][tag]
                continue
            for other_pop in self[other][tag]["create_pop"]:
                hasAttributeType = "pop_type" in other_pop
                hasAttributeReligion = "religion" in other_pop
                for this_pop in self[this][tag]["create_pop"]:
                    if other_pop["culture"] != this_pop["culture"]:
                        continue
                    if hasAttributeType:
                        if "pop_type" not in this_pop:
                            continue
                        if other_pop["pop_type"] != this_pop["pop_type"]:
                            continue
                    else:
                        if "pop_type" in this_pop:
                            continue
                    if hasAttributeReligion:
                        if "religion" not in this_pop:
                            continue
                        if other_pop["religion"] != this_pop["religion"]:
                            continue
                    else:
                        if "religion" in this_pop:
                            continue
                    this_pop["size"] = int(this_pop["size"]) + int(other_pop["size"])
                    break
                else:
                    self[this][tag]["create_pop"].append(other_pop)

    def get_str(self, state_id: str) -> str:
        """Serialize a single state's pops to Victoria 3 script format.

        Produces a nested script block of the form::

            s:STATE_123 = {
                USA = {
                    create_pop = {
                        culture = american
                        religion = protestant
                        pop_type = laborers
                        size = 1000
                    }
                }
            }

        If a tag has no pops (empty ``create_pop`` list), an empty
        ``create_pop = {}`` block is emitted to satisfy the game's parser.

        Args:
            state_id: The state key to serialize (e.g. ``"s:STATE_123"``).

        Returns:
            A script-format string for the requested state.
        """
        state_str = f"    {state_id} = {{\n"
        for tag in self[state_id].keys():
            state_str += f"        {tag} = {{\n"
            for pop in self[state_id][tag]["create_pop"]:
                state_str += f"            create_pop = {{\n"
                for key, value in pop.items():
                    state_str += f"                {key} = {value}\n"
                state_str += f"            }}\n"
            if len(self[state_id][tag]["create_pop"]) == 0:
                state_str += f"            create_pop = {{}}\n"
            state_str += f"        }}\n"
        state_str += f"    }}\n"

        return state_str

    def merge_states(self, merge_dict: dict):
        """Merge pops according to a state merge plan.

        Iterates over every diner/food pair in *merge_dict*.  For each pair
        where the food state exists in the collection, the food's pops are
        merged into the diner via :meth:`merge_state`, and the food state
        entry is then removed from the dictionary.

        Args:
            merge_dict: A dictionary mapping diner state IDs to lists of
                food state IDs, e.g.
                ``{"STATE_123": ["STATE_456", "STATE_789"]}``.  The ``s:``
                prefix is added internally.
        """
        for diner, food_list in merge_dict.items():
            for food in food_list:
                if ("s:" + food) in self.keys():
                    print(f"Merging {food} pop data into {diner}")
                    self.merge_state(("s:" + diner), ("s:" + food))
                    self.pop("s:" + food)

    def __str__(self) -> str:
        """Serialize the entire POPS tree to Victoria 3 script format.

        Returns:
            A string containing the full ``POPS = { ... }`` block.
        """
        pops_str = "POPS = {\n"
        for state_id in self.keys():
            pops_str += self.get_str(state_id)
        pops_str += "}\n"
        return pops_str

    def dump(self, dir):
        """Write the entire POPS tree to a file in Victoria 3 script format.

        The output file is written with UTF-8 BOM encoding (``utf-8-sig``),
        as required by Victoria 3.

        Args:
            dir: The output file path to write to.
        """
        with open(dir, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
