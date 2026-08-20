"""RunAcross public API."""

import logging
from importlib.metadata import PackageNotFoundError, version

from .executor import map_accounts
from .models import Account, AccountResult, ExecutionPhase, RunResults

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("runacross")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "Account",
    "AccountResult",
    "ExecutionPhase",
    "RunResults",
    "__version__",
    "map_accounts",
]
