"""Static downstream API checks; checked by mypy, never executed.

The ignores below are negative tests. With warn_unused_ignores enabled, the
check fails if an invalid assignment unexpectedly becomes accepted.
"""

from boto3.session import Session

from runacross import (
    Account,
    AccountRegionResult,
    AccountResult,
    Profile,
    RegionResults,
    ResultCallback,
    Role,
    RunResults,
    map_account_regions,
    map_accounts,
    show_progress,
)


def worker(session: Session, account: Account) -> int:
    return len(account.id)


def regional_worker(session: Session, account: Account, region: str) -> int:
    return len(account.id) + len(region)


def observer(record: AccountResult[int], *, completed: int, total: int) -> None:
    value: int = record.unwrap()
    del value


def regional_observer(
    record: AccountRegionResult[int], *, completed: int, total: int
) -> None:
    value: int = record.unwrap()
    del value


def broad_observer(record: object, *, completed: int, total: int) -> None:
    pass


def wrong_observer(record: AccountResult[int], *, completed: str, total: int) -> None:
    pass


def check_callback_argument(callback: ResultCallback[AccountResult[int]]) -> None:
    callback(Account("111111111111"), completed=1, total=1)  # type: ignore[arg-type]


def check_consumer_contract() -> None:
    callback: ResultCallback[AccountResult[int]] = observer
    callback = broad_observer
    callback = show_progress()
    callback = wrong_observer  # type: ignore[assignment]
    callback = regional_observer  # type: ignore[assignment]
    del callback

    results: RunResults[int] = map_accounts(
        worker, accounts=["111111111111"], auth=Role("audit"), on_result=observer
    )
    inferred = map_accounts(
        worker, accounts=[], auth=Profile("audit"), on_result=show_progress()
    )
    value: int = inferred[0].unwrap()
    wrong_value: str = inferred[0].unwrap()  # type: ignore[assignment]
    selected: tuple[AccountResult[int], ...] = results[:2]
    covariant: RunResults[object] = results
    del value, wrong_value, selected, covariant

    regions: RegionResults[int] = map_account_regions(
        regional_worker,
        accounts=[],
        regions=["eu-west-1"],
        auth=Role("audit"),
        on_result=regional_observer,
    )
    region_value: int = regions[0].unwrap()
    wrong_regions: RegionResults[str] = regions  # type: ignore[assignment]
    del region_value, wrong_regions

    map_accounts(worker, accounts=[], auth=Role("audit"), on_result=regional_observer)  # type: ignore[arg-type]
    map_account_regions(worker, accounts=[], regions=[], auth=Role("audit"))  # type: ignore[arg-type]
