from typing import Any, cast

import pytest

from vic3_state_merger.map_object_data import MapObjectData

pytestmark = pytest.mark.unit


def test_locator_remove_and_retarget(locator_data):
    m = MapObjectData(locator_data)
    assert len(m.get_all_instances()) == 3
    m.retarget_instance_id(2, 9)
    assert any(x.get("id") == 9 for x in m.instances_list)
    m.remove_instances_by_id([1, 9])
    assert len(m.instances_list) == 1 and "name" in m.instances_list[0]
    # pyradox collapses a singleton repeated block when converting back to
    # Python; the wrapper itself deliberately retains a list.
    assert m.game_object_locator_tree.to_python()["instances"]["name"] == "malformed"


def test_locator_validation():
    with pytest.raises(ValueError):
        MapObjectData({})
    with pytest.raises(TypeError):
        MapObjectData({"game_object_locator": "bad"})
    with pytest.raises(TypeError):
        MapObjectData(cast(Any, []))


def test_locator_dump_bom(tmp_path, locator_data):
    p = tmp_path / "m.txt"
    MapObjectData(locator_data).dump(p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
