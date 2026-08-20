from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar, cast, overload

_ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")

T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Account:
    """An AWS account targeted by an execution."""

    id: str
    name: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise TypeError("account id must be a string")
        if _ACCOUNT_ID_PATTERN.fullmatch(self.id) is None:
            raise ValueError("account id must contain exactly 12 ASCII digits")
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("account name must be a string or None")
        if self.email is not None and not isinstance(self.email, str):
            raise TypeError("account email must be a string or None")


AccountInput = str | Account


def coerce_accounts(accounts: Iterable[AccountInput]) -> tuple[Account, ...]:
    """Convert account IDs and Account instances into validated Accounts."""

    if isinstance(accounts, (str, bytes)):
        raise TypeError(
            "accounts must be an iterable of account IDs or Account objects"
        )

    coerced: list[Account] = []
    for index, account in enumerate(accounts):
        if isinstance(account, Account):
            coerced.append(account)
        elif isinstance(account, str):
            coerced.append(Account(id=account))
        else:
            raise TypeError(
                f"account at index {index} must be an account ID or Account object"
            )
    return tuple(coerced)


class ExecutionPhase(str, Enum):
    """The execution phase in which an account failed."""

    ASSUME_ROLE = "assume_role"
    WORKER = "worker"


@dataclass(frozen=True)
class AccountResult(Generic[T_co]):
    """The outcome of executing a callback for one AWS account."""

    account: Account
    value: T_co | None
    error: Exception | None
    duration_seconds: float
    phase: ExecutionPhase | None

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")
        if self.error is None and self.phase is not None:
            raise ValueError("a successful result cannot have a failure phase")
        if self.error is not None and self.phase is None:
            raise ValueError("a failed result must have a failure phase")
        if self.error is not None and self.value is not None:
            raise ValueError("a failed result cannot also contain a value")

    @property
    def success(self) -> bool:
        """Whether the callback completed successfully."""

        return self.error is None

    def unwrap(self) -> T_co:
        """Return the value or raise the account's stored exception."""

        if self.error is not None:
            raise self.error
        return cast(T_co, self.value)


class RunResults(Sequence[AccountResult[T_co]], Generic[T_co]):
    """An immutable, ordered collection of per-account results."""

    __slots__ = ("_results",)

    def __init__(self, results: Iterable[AccountResult[T_co]] = ()) -> None:
        self._results = tuple(results)

    @overload
    def __getitem__(self, index: int) -> AccountResult[T_co]: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[AccountResult[T_co], ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> AccountResult[T_co] | tuple[AccountResult[T_co], ...]:
        return self._results[index]

    def __iter__(self) -> Iterator[AccountResult[T_co]]:
        return iter(self._results)

    def __len__(self) -> int:
        return len(self._results)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"success_count={self.success_count}, "
            f"failure_count={self.failure_count})"
        )

    @property
    def successful(self) -> tuple[AccountResult[T_co], ...]:
        """Successful results in input order."""

        return tuple(result for result in self._results if result.success)

    @property
    def failed(self) -> tuple[AccountResult[T_co], ...]:
        """Failed results in input order."""

        return tuple(result for result in self._results if not result.success)

    @property
    def success_count(self) -> int:
        """Number of successful results."""

        return sum(result.success for result in self._results)

    @property
    def failure_count(self) -> int:
        """Number of failed results."""

        return len(self) - self.success_count
