# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest


@pytest.fixture
def application_logging():
    """Restore package logging after testing an application entry point."""
    import logging

    from vic3_state_merger import logging_config

    logger = logging.getLogger("vic3_state_merger")
    handlers = logger.handlers[:]
    owned = logging_config._owned_handlers[:]
    level, propagate = logger.level, logger.propagate
    yield logger
    for handler in logging_config._owned_handlers:
        if handler not in owned:
            handler.close()
    logger.handlers[:] = handlers
    logging_config._owned_handlers[:] = owned
    logger.setLevel(level)
    logger.propagate = propagate


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


@pytest.fixture
def spline_logs(caplog):
    """Inspect lazy log arguments without parsing rendered dictionary strings."""
    import logging

    caplog.set_level(logging.DEBUG, logger="vic3_state_merger")

    def captured(*categories):
        findings = []
        for record in caplog.records:
            if not record.name.startswith("vic3_state_merger.splines."):
                continue
            if record.msg == "%s (%s): %s":
                kind, category, details = record.args
                if category in categories:
                    findings.append({"kind": kind, "category": category, **details})
            elif record.msg in ("route: %s", "node_change: %s"):
                if record.msg.split(":")[0] in categories:
                    findings.append(record.args)
        return findings

    return captured
