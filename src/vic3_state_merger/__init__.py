# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vic3_state_merger")
except PackageNotFoundError:
    __version__ = "0.0.0"

from vic3_state_merger.buildings import Buildings
from vic3_state_merger.pops import Pops
from vic3_state_merger.sources import ASSETS, STAGES
from vic3_state_merger.state_merger import StateMerger
from vic3_state_merger.state_regions import StateRegion
from vic3_state_merger.states import States
from vic3_state_merger.trade import Trade

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "ASSETS",
    "STAGES",
    "Buildings",
    "Pops",
    "StateMerger",
    "StateRegion",
    "States",
    "Trade",
    "__version__",
]
