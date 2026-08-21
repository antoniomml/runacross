from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import NamedTuple, TypeVar, cast

from boto3.session import Session
from botocore.config import Config

from .auth import Auth, BoundAuth, resolve_auth
from .models import (
    Account,
    AccountInput,
    AccountRegion,
    AccountRegionResult,
    AccountResult,
    ExecutionPhase,
    RegionResults,
    RunResults,
    coerce_accounts,
    coerce_regions,
)
from .models import exclude_accounts as drop_accounts
from .models import exclude_regions as drop_regions
from .regions import list_enabled_regions

logger = logging.getLogger(__name__)

T = TypeVar("T")
ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")
_DEFAULT_ROLE_SESSION_NAME = "runacross"


class _Discovery(NamedTuple):
    targets: tuple[AccountRegion, ...]
    failure: AccountRegionResult[object] | None


def map_accounts(
    function: Callable[[Session, Account], T],
    *,
    accounts: Iterable[AccountInput],
    auth: Auth | None = None,
    role_name: str | None = None,
    role_session_name: str = _DEFAULT_ROLE_SESSION_NAME,
    external_id: str | None = None,
    duration_seconds: int | None = None,
    source_session: Session | None = None,
    botocore_config: Config | None = None,
    max_workers: int = 10,
    exclude_accounts: Iterable[AccountInput] = (),
) -> RunResults[T]:
    """Execute a callback concurrently in multiple AWS accounts."""

    _validate_function(function)
    _validate_max_workers(max_workers)
    resolved_auth = resolve_auth(
        auth=auth,
        role_name=role_name,
        role_session_name=role_session_name,
        external_id=external_id,
        duration_seconds=duration_seconds,
        source_session=source_session,
    )
    target_accounts = drop_accounts(coerce_accounts(accounts), exclude_accounts)
    if not target_accounts:
        return RunResults()

    bound = resolved_auth.bind(
        max_workers=max_workers,
        botocore_config=botocore_config,
    )
    return RunResults(
        _run_pool(
            target_accounts,
            lambda account: _execute_account(function, account, bound=bound),
            max_workers=max_workers,
        )
    )


def map_account_regions(
    function: Callable[[Session, Account, str], T],
    *,
    accounts: Iterable[AccountInput],
    auth: Auth | None = None,
    role_name: str | None = None,
    role_session_name: str = _DEFAULT_ROLE_SESSION_NAME,
    external_id: str | None = None,
    duration_seconds: int | None = None,
    source_session: Session | None = None,
    botocore_config: Config | None = None,
    max_workers: int = 10,
    regions: Iterable[str] | None = None,
    exclude_accounts: Iterable[AccountInput] = (),
    exclude_regions: Iterable[str] = (),
    discover_regions: bool = False,
) -> RegionResults[T]:
    """Execute a callback concurrently for each account and Region pair."""

    _validate_function(function)
    _validate_max_workers(max_workers)
    if not discover_regions and regions is None:
        raise TypeError(
            "map_account_regions requires regions=... or discover_regions=True"
        )

    resolved_auth = resolve_auth(
        auth=auth,
        role_name=role_name,
        role_session_name=role_session_name,
        external_id=external_id,
        duration_seconds=duration_seconds,
        source_session=source_session,
    )
    target_accounts = drop_accounts(coerce_accounts(accounts), exclude_accounts)
    requested_regions = None if regions is None else coerce_regions(regions)
    excluded_region_names = coerce_regions(exclude_regions)
    if not target_accounts:
        return RegionResults()

    bound = resolved_auth.bind(
        max_workers=max_workers,
        botocore_config=botocore_config,
    )

    if discover_regions:
        discoveries = _run_pool(
            target_accounts,
            lambda account: _discover_account(
                bound,
                account,
                requested_regions=requested_regions,
                excluded_regions=excluded_region_names,
                botocore_config=botocore_config,
            ),
            max_workers=max_workers,
        )
        targets = tuple(
            target
            for discovered in discoveries
            if discovered.failure is None
            for target in discovered.targets
        )
    else:
        assert requested_regions is not None
        selected_regions = drop_regions(requested_regions, excluded_region_names)
        targets = tuple(
            AccountRegion(account=account, region=region)
            for account in target_accounts
            for region in selected_regions
        )
        discoveries = None

    executed = _run_pool(
        targets,
        lambda target: _execute_account_region(function, target, bound=bound),
        max_workers=max_workers,
    )
    if discoveries is None:
        return RegionResults(executed)

    executed_index = 0
    ordered: list[AccountRegionResult[T]] = []
    for discovered in discoveries:
        if discovered.failure is not None:
            ordered.append(cast(AccountRegionResult[T], discovered.failure))
            continue
        next_index = executed_index + len(discovered.targets)
        ordered.extend(executed[executed_index:next_index])
        executed_index = next_index
    return RegionResults(ordered)


def _validate_function(function: object) -> None:
    if not callable(function):
        raise TypeError("function must be callable")


def _validate_max_workers(max_workers: int) -> None:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise TypeError("max_workers must be an integer")
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")


def _run_pool(
    items: Sequence[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_workers: int,
) -> list[ResultT]:
    if not items:
        return []

    ordered: list[ResultT | None] = [None] * len(items)
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="runacross",
    ) as executor:
        future_indexes = {
            executor.submit(worker, item): index for index, item in enumerate(items)
        }
        for future in as_completed(future_indexes):
            ordered[future_indexes[future]] = future.result()
    return cast(list[ResultT], ordered)


def _execute_account(
    function: Callable[[Session, Account], T],
    account: Account,
    *,
    bound: BoundAuth,
) -> AccountResult[T]:
    started_at = perf_counter()
    logger.debug("Authenticating account %s", account.id)

    try:
        session = bound.session_for(account)
    except Exception as error:
        return _account_failure(
            account,
            error,
            started_at,
            ExecutionPhase.AUTH,
            "Authentication failed for account %s after %.3fs",
        )

    logger.debug("Starting worker for account %s", account.id)
    try:
        value = function(session, account)
    except Exception as error:
        return _account_failure(
            account,
            error,
            started_at,
            ExecutionPhase.WORKER,
            "Worker failed for account %s after %.3fs",
        )

    duration = perf_counter() - started_at
    logger.debug("Completed account %s in %.3fs", account.id, duration)
    return AccountResult(
        account=account,
        value=value,
        error=None,
        duration_seconds=duration,
        phase=None,
    )


def _execute_account_region(
    function: Callable[[Session, Account, str], T],
    target: AccountRegion,
    *,
    bound: BoundAuth,
) -> AccountRegionResult[T]:
    started_at = perf_counter()
    logger.debug(
        "Authenticating account %s in %s",
        target.account.id,
        target.region,
    )

    try:
        session = bound.session_for(target.account, region=target.region)
    except Exception as error:
        return _account_region_failure(
            target,
            error,
            started_at,
            ExecutionPhase.AUTH,
            "Authentication failed for account %s in %s after %.3fs",
        )

    logger.debug(
        "Starting worker for account %s in %s",
        target.account.id,
        target.region,
    )
    try:
        value = function(session, target.account, target.region)
    except Exception as error:
        return _account_region_failure(
            target,
            error,
            started_at,
            ExecutionPhase.WORKER,
            "Worker failed for account %s in %s after %.3fs",
        )

    duration = perf_counter() - started_at
    logger.debug(
        "Completed account %s in %s in %.3fs",
        target.account.id,
        target.region,
        duration,
    )
    return AccountRegionResult(
        target=target,
        value=value,
        error=None,
        duration_seconds=duration,
        phase=None,
    )


def _discover_account(
    bound: BoundAuth,
    account: Account,
    *,
    requested_regions: tuple[str, ...] | None,
    excluded_regions: tuple[str, ...],
    botocore_config: Config | None,
) -> _Discovery:
    started_at = perf_counter()
    session: Session | None = None
    try:
        session = bound.session_for(account)
        enabled = list_enabled_regions(
            session=session,
            botocore_config=botocore_config,
        )
    except Exception as error:
        fallback = _discovery_failure_region(
            bound,
            session,
            requested_regions=requested_regions,
        )
        target = AccountRegion(account=account, region=fallback)
        return _Discovery(
            targets=(),
            failure=_account_region_failure(
                target,
                error,
                started_at,
                ExecutionPhase.AUTH,
                "Region discovery failed for account %s in %s after %.3fs",
            ),
        )

    if requested_regions is not None:
        allowed = set(requested_regions)
        enabled = [region for region in enabled if region in allowed]
    enabled = list(drop_regions(enabled, excluded_regions))
    logger.debug(
        "Account %s has %d Regions after filters",
        account.id,
        len(enabled),
    )
    return _Discovery(
        targets=tuple(
            AccountRegion(account=account, region=region) for region in enabled
        ),
        failure=None,
    )


def _discovery_failure_region(
    bound: BoundAuth,
    session: Session | None,
    *,
    requested_regions: tuple[str, ...] | None,
) -> str:
    if session is not None:
        region_name = session.region_name
        if isinstance(region_name, str) and region_name:
            return region_name
    reporting = bound.reporting_region()
    if reporting:
        return reporting
    if requested_regions:
        return requested_regions[0]
    return "us-east-1"


def _account_failure(
    account: Account,
    error: Exception,
    started_at: float,
    phase: ExecutionPhase,
    message: str,
) -> AccountResult[T]:
    duration = perf_counter() - started_at
    logger.debug(message, account.id, duration, exc_info=True)
    _clear_exception_tracebacks(error)
    return AccountResult(
        account=account,
        value=None,
        error=error,
        duration_seconds=duration,
        phase=phase,
    )


def _account_region_failure(
    target: AccountRegion,
    error: Exception,
    started_at: float,
    phase: ExecutionPhase,
    message: str,
) -> AccountRegionResult[T]:
    duration = perf_counter() - started_at
    logger.debug(
        message,
        target.account.id,
        target.region,
        duration,
        exc_info=True,
    )
    _clear_exception_tracebacks(error)
    return AccountRegionResult(
        target=target,
        value=None,
        error=error,
        duration_seconds=duration,
        phase=phase,
    )


def _clear_exception_tracebacks(error: BaseException) -> None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()

    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)
            current.__traceback__ = None
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
