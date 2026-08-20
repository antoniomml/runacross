from __future__ import annotations

import threading
from typing import Any, cast

import pytest
from boto3.session import Session
from botocore.config import Config

from runacross import Account, ExecutionPhase, map_accounts


class FakeMeta:
    partition = "aws"


class FakeStsClient:
    def __init__(self, failing_accounts: set[str] | None = None) -> None:
        self.meta = FakeMeta()
        self.failing_accounts = failing_accounts or set()
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self.requests.append(kwargs)

        account_id = kwargs["RoleArn"].split("::", 1)[1].split(":", 1)[0]
        if account_id in self.failing_accounts:
            raise PermissionError(f"cannot assume role in {account_id}")

        return {
            "Credentials": {
                "AccessKeyId": f"access-{account_id}",
                "SecretAccessKey": f"secret-{account_id}",
                "SessionToken": f"token-{account_id}",
            }
        }


class FakeSourceSession:
    def __init__(self, sts_client: FakeStsClient) -> None:
        self.region_name = "eu-west-1"
        self.sts_client = sts_client
        self.client_calls: list[tuple[str, Config]] = []

    def client(self, service_name: str, *, config: Config) -> FakeStsClient:
        self.client_calls.append((service_name, config))
        return self.sts_client


def source_session(
    *, failing_accounts: set[str] | None = None
) -> tuple[Session, FakeSourceSession]:
    fake = FakeSourceSession(FakeStsClient(failing_accounts))
    return cast(Session, fake), fake


def test_map_accounts_collects_mixed_results_without_cancelling() -> None:
    source, _ = source_session()

    def worker(_session: Session, account: Account) -> str:
        if account.id == "222222222222":
            raise RuntimeError("worker failed")
        return f"ok-{account.id}"

    results = map_accounts(
        worker,
        accounts=["111111111111", "222222222222", "333333333333"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=3,
    )

    assert results.success_count == 2
    assert results.failure_count == 1
    assert [result.account.id for result in results] == [
        "111111111111",
        "222222222222",
        "333333333333",
    ]
    assert results[0].value == "ok-111111111111"
    assert isinstance(results[1].error, RuntimeError)
    assert results[1].phase is ExecutionPhase.WORKER
    assert results[2].value == "ok-333333333333"


def test_assume_role_error_is_isolated_to_its_account() -> None:
    source, _ = source_session(failing_accounts={"222222222222"})

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111", "222222222222", "333333333333"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=3,
    )

    assert results.success_count == 2
    assert isinstance(results[1].error, PermissionError)
    assert results[1].phase is ExecutionPhase.ASSUME_ROLE


def test_results_preserve_input_order_after_out_of_order_completion() -> None:
    source, _ = source_session()
    second_completed = threading.Event()

    def worker(_session: Session, account: Account) -> str:
        if account.id == "111111111111":
            if not second_completed.wait(timeout=5):
                raise RuntimeError("second account did not complete")
        else:
            second_completed.set()
        return account.id

    results = map_accounts(
        worker,
        accounts=["111111111111", "222222222222"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=2,
    )

    assert [result.value for result in results] == [
        "111111111111",
        "222222222222",
    ]


def test_executor_runs_workers_concurrently_without_timing_assertions() -> None:
    source, _ = source_session()
    barrier = threading.Barrier(3, timeout=5)

    def worker(_session: Session, account: Account) -> str:
        barrier.wait()
        return account.id

    results = map_accounts(
        worker,
        accounts=["111111111111", "222222222222", "333333333333"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=3,
    )

    assert results.success_count == 3


def test_each_worker_receives_a_distinct_session() -> None:
    source, _ = source_session()
    received_sessions: list[Session] = []
    lock = threading.Lock()

    def worker(session: Session, account: Account) -> str:
        with lock:
            received_sessions.append(session)
        return account.id

    map_accounts(
        worker,
        accounts=["111111111111", "222222222222", "333333333333"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=3,
    )

    assert len({id(session) for session in received_sessions}) == 3
    assert {session.region_name for session in received_sessions} == {"eu-west-1"}


def test_empty_accounts_do_not_create_an_aws_client() -> None:
    source, fake_source = source_session()

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=[],
        role_name="SecurityAuditRole",
        source_session=source,
    )

    assert len(results) == 0
    assert fake_source.client_calls == []


def test_runacross_configures_the_shared_sts_client() -> None:
    source, fake_source = source_session()

    map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=25,
    )

    service_name, config = fake_source.client_calls[0]
    assert service_name == "sts"
    assert config.retries == {
        "mode": "standard",
        "total_max_attempts": 3,
    }
    assert config.max_pool_connections == 25


def test_worker_exception_traceback_is_not_retained() -> None:
    source, _ = source_session()

    def worker(_session: Session, _account: Account) -> None:
        raise RuntimeError("failed")

    results = map_accounts(
        worker,
        accounts=["111111111111"],
        role_name="SecurityAuditRole",
        source_session=source,
    )

    assert results[0].error is not None
    assert results[0].error.__traceback__ is None


@pytest.mark.parametrize("max_workers", [0, -1])
def test_map_accounts_rejects_invalid_worker_count(max_workers: int) -> None:
    source, _ = source_session()

    with pytest.raises(ValueError, match="at least 1"):
        map_accounts(
            lambda _session, account: account.id,
            accounts=[],
            role_name="SecurityAuditRole",
            source_session=source,
            max_workers=max_workers,
        )


def test_user_botocore_config_overrides_runacross_defaults() -> None:
    source, fake_source = source_session()
    user_config = Config(
        retries={
            "mode": "adaptive",
            "total_max_attempts": 8,
        },
        max_pool_connections=50,
    )

    map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        role_name="SecurityAuditRole",
        source_session=source,
        botocore_config=user_config,
    )

    config = fake_source.client_calls[0][1]
    assert config.retries == {
        "mode": "adaptive",
        "total_max_attempts": 8,
    }
    assert config.max_pool_connections == 50
