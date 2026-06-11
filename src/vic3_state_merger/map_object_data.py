from collections.abc import Iterable
from typing import cast

from pyradox import Tree


class MapObjectData(Tree):
    def __init__(self, source: Tree | dict):
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
        locator_dict = self.game_object_locator_tree.to_python()
        return locator_dict.get("instances", [])

    def remove_instances_by_id(self, state_ids: Iterable[int]):
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
        with open(file_path, "w", encoding="utf-8-sig") as file:
            file.write(str(self))
