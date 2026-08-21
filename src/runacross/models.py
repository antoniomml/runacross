from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar, cast, overload

_ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
_REGION_PATTERN = re.compile(r"[a-z]{2}(-[a-z0-9]+)+-\d+\Z")

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

    def __repr__(self) -> str:
        parts = [f"id={self.id!r}"]
        if self.name is not None:
            parts.append(f"name={self.name!r}")
        if self.email is not None:
            parts.append("email=<redacted>")
        return f"{type(self).__name__}({', '.join(parts)})"


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


def exclude_accounts(
    accounts: Iterable[Account],
    excluded: Iterable[AccountInput],
) -> tuple[Account, ...]:
    """Return accounts whose IDs are not in the exclusion list, preserving order."""

    excluded_ids = {account.id for account in coerce_accounts(excluded)}
    return tuple(account for account in accounts if account.id not in excluded_ids)


def coerce_regions(regions: Iterable[str]) -> tuple[str, ...]:
    """Validate Region names."""

    if isinstance(regions, (str, bytes)):
        raise TypeError("regions must be an iterable of Region names")

    coerced: list[str] = []
    for index, region in enumerate(regions):
        if not isinstance(region, str):
            raise TypeError(f"region at index {index} must be a string")
        if _REGION_PATTERN.fullmatch(region) is None:
            raise ValueError(
                f"region at index {index} must be an AWS Region name such as eu-west-1"
            )
        coerced.append(region)
    return tuple(coerced)


def exclude_regions(
    regions: Iterable[str],
    excluded: Iterable[str],
) -> tuple[str, ...]:
    """Return Region names that are not in the exclusion list, preserving order."""

    excluded_names = set(coerce_regions(excluded))
    return tuple(region for region in regions if region not in excluded_names)


@dataclass(frozen=True, slots=True)
class AccountRegion:
    """An AWS account and Region pair targeted by an execution."""

    account: Account
    region: str

    def __post_init__(self) -> None:
        if not isinstance(self.account, Account):
            raise TypeError("account must be an Account")
        if not isinstance(self.region, str):
            raise TypeError("region must be a string")
        if _REGION_PATTERN.fullmatch(self.region) is None:
            raise ValueError("region must be an AWS Region name such as eu-west-1")


class ExecutionPhase(str, Enum):
    """The execution phase in which a target failed."""

    AUTH = "auth"
    WORKER = "worker"


def _validate_outcome(
    *,
    value: object,
    error: Exception | None,
    duration_seconds: float,
    phase: ExecutionPhase | None,
) -> None:
    if duration_seconds < 0:
        raise ValueError("duration_seconds cannot be negative")
    if error is None and phase is not None:
        raise ValueError("a successful result cannot have a failure phase")
    if error is not None and phase is None:
        raise ValueError("a failed result must have a failure phase")
    if error is not None and value is not None:
        raise ValueError("a failed result cannot also contain a value")


@dataclass(frozen=True)
class AccountResult(Generic[T_co]):
    """The outcome of executing a callback for one AWS account."""

    account: Account
    value: T_co | None
    error: Exception | None
    duration_seconds: float
    phase: ExecutionPhase | None

    def __post_init__(self) -> None:
        _validate_outcome(
            value=self.value,
            error=self.error,
            duration_seconds=self.duration_seconds,
            phase=self.phase,
        )

    @property
    def success(self) -> bool:
        """Whether the callback completed successfully."""

        return self.error is None

    def unwrap(self) -> T_co:
        """Return the value or raise the stored exception."""

        if self.error is not None:
            raise self.error
        return cast(T_co, self.value)


@dataclass(frozen=True)
class AccountRegionResult(Generic[T_co]):
    """The outcome of executing a callback for one account and Region pair."""

    target: AccountRegion
    value: T_co | None
    error: Exception | None
    duration_seconds: float
    phase: ExecutionPhase | None

    def __post_init__(self) -> None:
        if not isinstance(self.target, AccountRegion):
            raise TypeError("target must be an AccountRegion")
        _validate_outcome(
            value=self.value,
            error=self.error,
            duration_seconds=self.duration_seconds,
            phase=self.phase,
        )

    @property
    def account(self) -> Account:
        """The account from the result identity."""

        return self.target.account

    @property
    def region(self) -> str:
        """The Region from the result identity."""

        return self.target.region

    @property
    def success(self) -> bool:
        """Whether the callback completed successfully."""

        return self.error is None

    def unwrap(self) -> T_co:
        """Return the value or raise the stored exception."""

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


class RegionResults(Sequence[AccountRegionResult[T_co]], Generic[T_co]):
    """An immutable, ordered collection of per-account-and-Region results."""

    __slots__ = ("_results",)

    def __init__(self, results: Iterable[AccountRegionResult[T_co]] = ()) -> None:
        self._results = tuple(results)

    @overload
    def __getitem__(self, index: int) -> AccountRegionResult[T_co]: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[AccountRegionResult[T_co], ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> AccountRegionResult[T_co] | tuple[AccountRegionResult[T_co], ...]:
        return self._results[index]

    def __iter__(self) -> Iterator[AccountRegionResult[T_co]]:
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
    def successful(self) -> tuple[AccountRegionResult[T_co], ...]:
        """Successful results in input order."""

        return tuple(result for result in self._results if result.success)

    @property
    def failed(self) -> tuple[AccountRegionResult[T_co], ...]:
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
