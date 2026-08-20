"""RunAcross public API."""

import logging

from .executor import map_accounts
from .models import Account, AccountResult, ExecutionPhase, RunResults

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Account",
    "AccountResult",
    "ExecutionPhase",
    "RunResults",
    "map_accounts",
]
