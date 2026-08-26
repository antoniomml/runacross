from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, cast, overload

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


def coerce_limit(limit: int | None) -> int | None:
    """Validate an optional account-list limit."""

    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer or None")
    if limit < 0:
        raise ValueError("limit cannot be negative")
    return limit


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


def _aws_error_code(error: Exception | None) -> str | None:
    """Return a structured AWS error code without parsing exception text.

    Botocore ``ClientError`` values expose the code at
    ``error.response["Error"]["Code"]``. Other exceptions return ``None``.
    """

    if error is None:
        return None
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None
    details = response.get("Error")
    if not isinstance(details, Mapping):
        return None
    code = details.get("Code")
    if isinstance(code, str) and code:
        return code
    return None


def _outcome_dict(
    *,
    account: Account,
    value: object,
    error: Exception | None,
    duration_seconds: float,
    phase: ExecutionPhase | None,
    region: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "account_id": account.id,
        "account_name": account.name,
        "success": error is None,
        "value": value if error is None else None,
        "error_type": type(error).__name__ if error is not None else None,
        "error_message": str(error) if error is not None else None,
        "error_code": _aws_error_code(error),
        "phase": None if phase is None else phase.value,
        "duration_seconds": duration_seconds,
    }
    if region is not None:
        payload["region"] = region
    return payload


def _failures_by_phase(
    results: Iterable[AccountResult[Any] | AccountRegionResult[Any]],
) -> dict[ExecutionPhase, tuple[AccountResult[Any] | AccountRegionResult[Any], ...]]:
    grouped: dict[
        ExecutionPhase, list[AccountResult[Any] | AccountRegionResult[Any]]
    ] = {phase: [] for phase in ExecutionPhase}
    for result in results:
        if not result.success and result.phase is not None:
            grouped[result.phase].append(result)
    return {phase: tuple(items) for phase, items in grouped.items()}


def _summary(
    results: Sequence[AccountResult[Any] | AccountRegionResult[Any]],
) -> dict[str, Any]:
    by_phase = _failures_by_phase(results)
    return {
        "total": len(results),
        "success_count": sum(result.success for result in results),
        "failure_count": sum(not result.success for result in results),
        "failures_by_phase": {
            phase.value: len(items) for phase, items in by_phase.items()
        },
    }


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

    @property
    def error_code(self) -> str | None:
        """Structured AWS error code, if the stored exception exposes one."""

        return _aws_error_code(self.error)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record without credentials or email."""

        return _outcome_dict(
            account=self.account,
            value=self.value,
            error=self.error,
            duration_seconds=self.duration_seconds,
            phase=self.phase,
        )


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

    @property
    def error_code(self) -> str | None:
        """Structured AWS error code, if the stored exception exposes one."""

        return _aws_error_code(self.error)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record without credentials or email."""

        return _outcome_dict(
            account=self.account,
            value=self.value,
            error=self.error,
            duration_seconds=self.duration_seconds,
            phase=self.phase,
            region=self.region,
        )


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

    def to_dicts(self) -> list[dict[str, Any]]:
        """Convert results to dictionaries for JSON, CSV, or logging."""

        return [result.to_dict() for result in self._results]

    def failures_by_phase(
        self,
    ) -> dict[ExecutionPhase, tuple[AccountResult[T_co], ...]]:
        """Group failed results by phase, preserving input order."""

        grouped = _failures_by_phase(self._results)
        return {
            phase: cast(tuple[AccountResult[T_co], ...], items)
            for phase, items in grouped.items()
        }

    def summary(self) -> dict[str, Any]:
        """Return counts suitable for logs or reports."""

        return _summary(self._results)


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

    def to_dicts(self) -> list[dict[str, Any]]:
        """Convert results to dictionaries for JSON, CSV, or logging."""

        return [result.to_dict() for result in self._results]

    def failures_by_phase(
        self,
    ) -> dict[ExecutionPhase, tuple[AccountRegionResult[T_co], ...]]:
        """Group failed results by phase, preserving input order."""

        grouped = _failures_by_phase(self._results)
        return {
            phase: cast(tuple[AccountRegionResult[T_co], ...], items)
            for phase, items in grouped.items()
        }

    def summary(self) -> dict[str, Any]:
        """Return counts suitable for logs or reports."""

        return _summary(self._results)
