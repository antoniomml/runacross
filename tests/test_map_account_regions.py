from __future__ import annotations

import threading
from typing import Any, cast

import pytest
from boto3.session import Session
from botocore.config import Config

from runacross import (
    Account,
    ExecutionPhase,
    map_account_regions,
)
from runacross.models import AccountRegion


class FakeMeta:
    partition = "aws"


class FakeStsClient:
    def __init__(self) -> None:
        self.meta = FakeMeta()
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self.requests.append(kwargs)
        account_id = kwargs["RoleArn"].split("::", 1)[1].split(":", 1)[0]
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

    def client(self, service_name: str, *, config: Config) -> FakeStsClient:
        del service_name, config
        return self.sts_client


class FakeBoundAuth:
    def __init__(
        self,
        *,
        region: str = "eu-west-1",
        fail_accounts: set[str] | None = None,
        enabled_regions: dict[str, list[str]] | None = None,
        discover_error: Exception | None = None,
    ) -> None:
        self.region = region
        self.fail_accounts = fail_accounts or set()
        self.enabled_regions = enabled_regions or {}
        self.discover_error = discover_error
        self.session_calls: list[tuple[str, str | None]] = []

    def reporting_region(self) -> str | None:
        return self.region

    def session_for(self, account: Account, *, region: str | None = None) -> Session:
        self.session_calls.append((account.id, region))
        if account.id in self.fail_accounts:
            raise PermissionError(f"cannot authenticate {account.id}")
        return cast(
            Session,
            FakeAccountSession(
                region_name=region or self.region,
                enabled=self.enabled_regions.get(account.id, []),
                discover_error=self.discover_error,
            ),
        )


class FakeAuth:
    def __init__(self, bound: FakeBoundAuth) -> None:
        self.bound = bound

    def bind(
        self,
        *,
        max_workers: int,
        botocore_config: Config | None,
    ) -> FakeBoundAuth:
        del max_workers, botocore_config
        return self.bound


class FakePaginator:
    def __init__(self, regions: list[str], error: Exception | None = None) -> None:
        self.regions = regions
        self.error = error

    def paginate(self, **_kwargs: Any) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return [{"Regions": [{"RegionName": name} for name in self.regions]}]


class FakeAccountSession:
    def __init__(
        self,
        *,
        region_name: str,
        enabled: list[str],
        discover_error: Exception | None,
    ) -> None:
        self.region_name = region_name
        self.enabled = enabled
        self.discover_error = discover_error

    def client(self, service_name: str, *, config: Config) -> Any:
        del config
        assert service_name == "account"
        return FakeAccountClient(self.enabled, self.discover_error)


class FakeAccountClient:
    def __init__(self, regions: list[str], error: Exception | None) -> None:
        self.regions = regions
        self.error = error

    def get_paginator(self, operation_name: str) -> FakePaginator:
        assert operation_name == "list_regions"
        return FakePaginator(self.regions, self.error)


def test_map_account_regions_runs_cartesian_product_in_input_order() -> None:
    bound = FakeBoundAuth()
    results = map_account_regions(
        lambda session, account, region: f"{account.id}:{region}:{session.region_name}",
        accounts=["111111111111", "222222222222"],
        regions=["eu-west-1", "us-east-1"],
        auth=FakeAuth(bound),
    )

    assert [(result.account.id, result.region, result.value) for result in results] == [
        ("111111111111", "eu-west-1", "111111111111:eu-west-1:eu-west-1"),
        ("111111111111", "us-east-1", "111111111111:us-east-1:us-east-1"),
        ("222222222222", "eu-west-1", "222222222222:eu-west-1:eu-west-1"),
        ("222222222222", "us-east-1", "222222222222:us-east-1:us-east-1"),
    ]
    assert isinstance(results[0].target, AccountRegion)


def test_map_account_regions_exclude_filters() -> None:
    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111", "222222222222", "333333333333"],
        regions=["eu-west-1", "us-east-1", "ap-southeast-2"],
        auth=FakeAuth(FakeBoundAuth()),
        exclude_accounts=["222222222222"],
        exclude_regions=["ap-southeast-2"],
    )

    assert [(result.account.id, result.region) for result in results] == [
        ("111111111111", "eu-west-1"),
        ("111111111111", "us-east-1"),
        ("333333333333", "eu-west-1"),
        ("333333333333", "us-east-1"),
    ]


def test_map_account_regions_requires_regions_or_discovery() -> None:
    with pytest.raises(TypeError, match="regions="):
        map_account_regions(
            lambda _session, _account, region: region,
            accounts=["111111111111"],
            auth=FakeAuth(FakeBoundAuth()),
        )


def test_map_account_regions_isolates_worker_failures() -> None:
    def worker(_session: Session, account: Account, region: str) -> str:
        if region == "us-east-1":
            raise RuntimeError("worker failed")
        return f"{account.id}:{region}"

    results = map_account_regions(
        worker,
        accounts=["111111111111"],
        regions=["eu-west-1", "us-east-1"],
        auth=FakeAuth(FakeBoundAuth()),
    )

    assert results[0].success is True
    assert results[1].success is False
    assert results[1].phase is ExecutionPhase.WORKER
    assert results.success_count == 1
    assert results.failure_count == 1


def test_map_account_regions_isolates_auth_failures() -> None:
    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111", "222222222222"],
        regions=["eu-west-1"],
        auth=FakeAuth(FakeBoundAuth(fail_accounts={"222222222222"})),
    )

    assert results[0].success is True
    assert results[1].success is False
    assert results[1].phase is ExecutionPhase.AUTH
    assert results[1].region == "eu-west-1"


def test_map_account_regions_discovers_enabled_regions_per_account() -> None:
    bound = FakeBoundAuth(
        enabled_regions={
            "111111111111": ["eu-west-1", "us-east-1", "ap-east-1"],
            "222222222222": ["eu-west-1"],
        }
    )

    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111", "222222222222"],
        auth=FakeAuth(bound),
        discover_regions=True,
        exclude_regions=["ap-east-1"],
    )

    assert [(result.account.id, result.region) for result in results] == [
        ("111111111111", "eu-west-1"),
        ("111111111111", "us-east-1"),
        ("222222222222", "eu-west-1"),
    ]


def test_map_account_regions_discovery_allowlist() -> None:
    bound = FakeBoundAuth(
        enabled_regions={
            "111111111111": ["eu-west-1", "us-east-1", "ap-southeast-2"],
        }
    )

    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111"],
        regions=["eu-west-1", "ap-southeast-2"],
        auth=FakeAuth(bound),
        discover_regions=True,
    )

    assert [result.region for result in results] == ["eu-west-1", "ap-southeast-2"]


def test_map_account_regions_discovery_failure_is_isolated() -> None:
    bound = FakeBoundAuth(
        enabled_regions={"111111111111": ["eu-west-1"]},
        fail_accounts={"222222222222"},
    )

    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111", "222222222222"],
        auth=FakeAuth(bound),
        discover_regions=True,
    )

    assert results[0].success is True
    assert results[0].region == "eu-west-1"
    assert results[1].success is False
    assert results[1].phase is ExecutionPhase.AUTH
    assert results[1].account.id == "222222222222"


def test_map_account_regions_list_regions_failure_uses_session_region() -> None:
    bound = FakeBoundAuth(
        region="eu-central-1",
        enabled_regions={"111111111111": ["eu-west-1"]},
        discover_error=RuntimeError("list failed"),
    )

    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111"],
        auth=FakeAuth(bound),
        discover_regions=True,
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].region == "eu-central-1"


def test_map_account_regions_auth_failure_falls_back_to_requested_region() -> None:
    bound = FakeBoundAuth(fail_accounts={"111111111111"})
    bound.region = None  # type: ignore[assignment]

    results = map_account_regions(
        lambda _session, account, region: f"{account.id}:{region}",
        accounts=["111111111111"],
        regions=["ap-southeast-2"],
        auth=FakeAuth(bound),
        discover_regions=True,
    )

    assert results[0].success is False
    assert results[0].region == "ap-southeast-2"


def test_map_account_regions_assumes_role_once_per_account() -> None:
    sts = FakeStsClient()
    source = cast(Session, FakeSourceSession(sts))

    results = map_account_regions(
        lambda session, account, region: f"{account.id}:{session.region_name}:{region}",
        accounts=["111111111111", "222222222222"],
        regions=["eu-west-1", "us-east-1"],
        role_name="SecurityAuditRole",
        source_session=source,
        max_workers=4,
    )

    assert results.success_count == 4
    assert len(sts.requests) == 2
    assert {result.value for result in results} == {
        "111111111111:eu-west-1:eu-west-1",
        "111111111111:us-east-1:us-east-1",
        "222222222222:eu-west-1:eu-west-1",
        "222222222222:us-east-1:us-east-1",
    }


def test_map_account_regions_empty_accounts_do_not_bind_auth() -> None:
    bound = FakeBoundAuth()

    results = map_account_regions(
        lambda _session, _account, region: region,
        accounts=["111111111111"],
        regions=["eu-west-1"],
        auth=FakeAuth(bound),
        exclude_accounts=["111111111111"],
    )

    assert list(results) == []
    assert bound.session_calls == []


def test_map_account_regions_rejects_non_callable_function() -> None:
    with pytest.raises(TypeError, match="function must be callable"):
        map_account_regions(
            "not-a-function",  # type: ignore[arg-type]
            accounts=["111111111111"],
            regions=["eu-west-1"],
            auth=FakeAuth(FakeBoundAuth()),
        )
