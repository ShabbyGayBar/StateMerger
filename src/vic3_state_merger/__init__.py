try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:  # Python <3.8 fallback if needed
    from importlib_metadata import version, PackageNotFoundError  # type: ignore

try:
    __version__ = version("vic3_state_merger")
except PackageNotFoundError:
    __version__ = "0.0.0"

from vic3_state_merger.state_merger import StateMerger, clear_mod_dir
from vic3_state_merger.state_regions import StateRegion
from vic3_state_merger.buildings import Buildings
from vic3_state_merger.pops import Pops
from vic3_state_merger.states import States
from vic3_state_merger.trade import Trade
