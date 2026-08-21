"""RunAcross public API."""

import logging
from importlib.metadata import PackageNotFoundError, version

from .auth import Profile, Role
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
    "ExecutionPhase",
    "Profile",
    "RegionResults",
    "Role",
    "RunResults",
    "__version__",
    "map_account_regions",
    "map_accounts",
]
