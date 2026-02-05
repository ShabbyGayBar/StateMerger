try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:  # Python <3.8 fallback if needed
    from importlib_metadata import version, PackageNotFoundError  # type: ignore

try:
    __version__ = version("vic3_state_merger")
except PackageNotFoundError:
    __version__ = "0.0.0"

from .state_merger import StateMerger, clear_mod_dir
from .state_regions import StateRegion
from .buildings import Buildings
from .pops import Pops
from .states import States
from .trade import Trade
