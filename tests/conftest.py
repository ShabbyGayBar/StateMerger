import pytest


@pytest.fixture
def building_data():
    return {
        "BUILDINGS": {
            "s:A": {
                "USA": {
                    "create_building": {
                        "building": "building_tooling_workshops",
                        "add_ownership": {
                            "building": {
                                "type": "privately_owned",
                                "country": "c:USA",
                                "levels": "2",
                                "region": '"A"',
                            }
                        },
                        "reserves": "7",
                        "activate_production_methods": "pm_steam_engine",
                    }
                }
            }
        }
    }


@pytest.fixture
def states_data():
    return {
        "STATES": {
            "s:A": {
                "create_state": {"country": "c:USA", "owned_provinces": "p1"},
                "add_homeland": "cul_a",
                "add_claim": "c:USA",
            },
            "s:B": {
                "create_state": {"country": "c:USA", "owned_provinces": ("p2", "p3")},
                "add_homeland": ("cul_b", "cul_a"),
                "add_claim": "c:FRA",
            },
        }
    }


@pytest.fixture
def pops_data():
    return {
        "POPS": {
            "s:A": {
                "USA": {
                    "create_pop": {
                        "culture": "a",
                        "pop_type": "laborers",
                        "religion": "r",
                        "size": "10",
                    }
                }
            },
            "s:B": {
                "USA": {
                    "create_pop": [
                        {
                            "culture": "a",
                            "pop_type": "laborers",
                            "religion": "r",
                            "size": 5,
                        },
                        {"culture": "b", "size": 2},
                    ]
                }
            },
        }
    }


@pytest.fixture
def trade_data():
    return {
        "TRADE": {
            "s:A": {"R": {"grain": {"add_exports": "2", "add_imports": 1}}},
            "s:B": {
                "R": {
                    "grain": {"add_exports": 3, "add_imports": "4"},
                    "iron": {"add_exports": "bad"},
                }
            },
        }
    }


@pytest.fixture
def region_data():
    def make(name, ident, provinces, **extra):
        d = {
            "id": ident,
            "subsistence_building": "building_subsistence_farms",
            "provinces": provinces,
            "arable_land": 2,
            "arable_resources": "bg_ranches",
        }
        d.update(extra)
        return {name: d}

    return make


@pytest.fixture
def locator_data():
    return {
        "game_object_locator": {
            "instances": [{"id": 1, "x": 2}, {"id": "2"}, {"name": "malformed"}]
        }
    }
