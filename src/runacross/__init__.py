"""RunAcross public API."""

import logging
from importlib.metadata import PackageNotFoundError, version

from .auth import Profile, Role
from .exceptions import ConfigError, RunAcrossError
from .executor import map_account_regions, map_accounts
from .models import (
    Account,
    AccountRegion,
    AccountRegionResult,
    AccountResult,
    ExecutionPhase,
    RegionResults,
    RunResults,
)
from .progress import show_progress

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("runacross")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "Account",
    "AccountRegion",
    "AccountRegionResult",
    "AccountResult",
    "ConfigError",
    "ExecutionPhase",
    "Profile",
    "RegionResults",
    "Role",
    "RunAcrossError",
    "RunResults",
    "__version__",
    "map_account_regions",
    "map_accounts",
    "show_progress",
]
