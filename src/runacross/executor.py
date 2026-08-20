from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import TypeVar, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .models import (
    Account,
    AccountInput,
    AccountResult,
    ExecutionPhase,
    RunResults,
    coerce_accounts,
)
from .sts import (
    StsClient,
    assume_role_session,
    build_client_config,
    validate_assume_role_options,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def map_accounts(
    function: Callable[[Session, Account], T],
    *,
    accounts: Iterable[AccountInput],
    role_name: str,
    role_session_name: str = "runacross",
    external_id: str | None = None,
    duration_seconds: int | None = None,
    source_session: Session | None = None,
    botocore_config: Config | None = None,
    max_workers: int = 10,
) -> RunResults[T]:
    """Execute a callback concurrently in multiple AWS accounts."""

    if not callable(function):
        raise TypeError("function must be callable")
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise TypeError("max_workers must be an integer")
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    validate_assume_role_options(
        role_name=role_name,
        role_session_name=role_session_name,
        external_id=external_id,
        duration_seconds=duration_seconds,
    )
    target_accounts = coerce_accounts(accounts)
    if not target_accounts:
        return RunResults()

    session = source_session if source_session is not None else boto3.Session()
    source_region = session.region_name
    if not source_region:
        raise ValueError(
            "source session must have a region; set AWS_DEFAULT_REGION, "
            "a profile region, or pass a Session with region_name"
        )
    client_config = build_client_config(
        max_pool_connections=max_workers,
        user_config=botocore_config,
    )
    sts_client = cast(
        StsClient,
        session.client("sts", config=client_config),
    )

    ordered: list[AccountResult[T] | None] = [None] * len(target_accounts)
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="runacross",
    ) as executor:
        future_indexes = {
            executor.submit(
                _execute_account,
                function,
                account,
                sts_client=sts_client,
                role_name=role_name,
                role_session_name=role_session_name,
                external_id=external_id,
                duration_seconds=duration_seconds,
                region_name=source_region,
            ): index
            for index, account in enumerate(target_accounts)
        }

        for future in as_completed(future_indexes):
            ordered[future_indexes[future]] = future.result()

    return RunResults(cast(list[AccountResult[T]], ordered))


def _execute_account(
    function: Callable[[Session, Account], T],
    account: Account,
    *,
    sts_client: StsClient,
    role_name: str,
    role_session_name: str,
    external_id: str | None,
    duration_seconds: int | None,
    region_name: str,
) -> AccountResult[T]:
    started_at = perf_counter()
    logger.debug("Assuming role into account %s", account.id)

    try:
        target_session = assume_role_session(
            sts_client,
            account,
            role_name=role_name,
            role_session_name=role_session_name,
            external_id=external_id,
            duration_seconds=duration_seconds,
            region_name=region_name,
        )
    except Exception as error:
        duration = perf_counter() - started_at
        logger.debug(
            "AssumeRole failed for account %s after %.3fs",
            account.id,
            duration,
            exc_info=True,
        )
        _clear_exception_tracebacks(error)
        return AccountResult(
            account=account,
            value=None,
            error=error,
            duration_seconds=duration,
            phase=ExecutionPhase.ASSUME_ROLE,
        )

    logger.debug("Starting worker for account %s", account.id)
    try:
        value = function(target_session, account)
    except Exception as error:
        duration = perf_counter() - started_at
        logger.debug(
            "Worker failed for account %s after %.3fs",
            account.id,
            duration,
            exc_info=True,
        )
        _clear_exception_tracebacks(error)
        return AccountResult(
            account=account,
            value=None,
            error=error,
            duration_seconds=duration,
            phase=ExecutionPhase.WORKER,
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
