"""Map-object locator data parsing and manipulation for Victoria 3 state merging.

This module provides the :class:`MapObjectData` class, which wraps a
``pyradox.Tree` representing a Victoria 3 map-object data file (e.g.
``game_object_locator.txt``).  Each map object *instance* carries an ``id``
field that corresponds to a state ID; when states are merged, instances
belonging to absorbed states must either be removed or retargeted to the
surviving state.

The class exposes helpers to:

- Enumerate all instances from the ``game_object_locator`` subtree.
- Remove instances whose IDs belong to a set of deleted states.
- Retarget a single instance ID from a source (absorbed) state to a target
  (surviving) state.

Output is written in Vic3 script format with UTF-8 BOM encoding.
"""

from collections.abc import Iterable
from typing import cast
from pyradox import Tree


class MapObjectData(Tree):
    """Represents a Victoria 3 map-object data file rooted at ``game_object_locator``.

    The underlying tree is a ``pyradox.Tree`` whose top-level key
    ``game_object_locator`` contains an ``instances`` list.  Each instance
    is a dictionary that (among other fields) carries an ``id`` integer
    corresponding to a state ID on the game map.

    Attributes:
        game_object_locator_tree: The ``pyradox.Tree`` subtree stored under
            the ``game_object_locator`` key.
        instances_list: A plain Python list of instance dictionaries extracted
            from ``game_object_locator_tree``.  Kept in sync with the tree
            after every mutation.
    """

    def __init__(self, source: Tree | dict):
        """Initialize a :class:`MapObjectData` from a parsed tree or dict.

        Args:
            source: A ``pyradox.Tree`` or ``dict`` containing the full
                map-object data.  Must include a ``game_object_locator``
                key whose value is a ``pyradox.Tree`` (or nested dict).

        Raises:
            TypeError: If *source* is neither a ``Tree`` nor a ``dict``.
            ValueError: If the tree is missing the ``game_object_locator``
                key or its value is not a ``Tree``.
        """
        super().__init__()

        if isinstance(source, Tree):
            tree_source = source
        elif isinstance(source, dict):
            tree_source = Tree(source)
        else:
            raise TypeError(
                "MapObjectData can only be initialized with a Tree or a dict"
            )

        if "game_object_locator" not in tree_source:
            raise ValueError(
                "Invalid map object data: missing 'game_object_locator' key"
            )

        self.update(tree_source)
        game_object_locator_tree = cast(Tree, self["game_object_locator"])
        if not isinstance(game_object_locator_tree, Tree):
            raise ValueError(
                "Invalid map object data: 'game_object_locator' must be a Tree"
            )
        self.game_object_locator_tree: Tree = game_object_locator_tree
        self.instances_list = self.get_all_instances()

    def get_all_instances(self):
        """Return the list of instance dicts from the ``game_object_locator`` subtree.

        Returns:
            A list of dictionaries, each representing one map-object instance.
            Returns an empty list if the ``instances`` key is absent.
        """
        locator_dict = self.game_object_locator_tree.to_python()
        return locator_dict.get("instances", [])

    def remove_instances_by_id(self, state_ids: Iterable[int]):
        """Remove all instances whose ``id`` matches one of the given state IDs.

        After removal the internal tree, ``game_object_locator_tree``, and
        ``instances_list`` are all updated to reflect the filtered set.

        Args:
            state_ids: An iterable of integer state IDs whose instances
                should be removed.
        """
        state_id_set = {int(state_id) for state_id in state_ids}
        locator_dict = self.game_object_locator_tree.to_python()
        filtered_instances = []
        for instance in locator_dict.get("instances", []):
            try:
                instance_id = int(instance["id"])
            except (KeyError, TypeError, ValueError):
                filtered_instances.append(instance)
                continue
            if instance_id not in state_id_set:
                filtered_instances.append(instance)

        locator_dict["instances"] = filtered_instances
        rebuilt_tree = Tree(locator_dict)
        self["game_object_locator"] = rebuilt_tree
        self.game_object_locator_tree = rebuilt_tree
        self.instances_list = filtered_instances

    def retarget_instance_id(self, source_id: int, target_id: int):
        """Retarget all instances with ``id`` == *source_id* to *target_id*.

        This is used when an absorbed state's map objects should be
        reassigned to the surviving (diner) state after a merge.

        After retargeting the internal tree, ``game_object_locator_tree``,
        and ``instances_list`` are all updated.

        Args:
            source_id: The state ID to search for (the absorbed state).
            target_id: The state ID to replace it with (the surviving state).
        """
        source_id = int(source_id)
        target_id = int(target_id)
        locator_dict = self.game_object_locator_tree.to_python()
        retargeted_instances = []
        for instance in locator_dict.get("instances", []):
            try:
                instance_id = int(instance["id"])
            except (KeyError, TypeError, ValueError):
                retargeted_instances.append(instance)
                continue
            if instance_id == source_id:
                instance = dict(instance)
                instance["id"] = target_id
            retargeted_instances.append(instance)

        locator_dict["instances"] = retargeted_instances
        rebuilt_tree = Tree(locator_dict)
        self["game_object_locator"] = rebuilt_tree
        self.game_object_locator_tree = rebuilt_tree
        self.instances_list = retargeted_instances

    def dump(self, file_path: str):
        """Write the map-object data to a file in Vic3 script format.

        The file is encoded as UTF-8 with a BOM prefix, consistent with
        other Victoria 3 mod output files.

        Args:
            file_path: Destination file path.
        """
        with open(file_path, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
