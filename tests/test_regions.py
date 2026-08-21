from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import pytest
from boto3.session import Session
from botocore.config import Config

from runacross.regions import list_enabled_regions


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.paginate_calls: list[dict[str, Any]] = []

    def paginate(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        self.paginate_calls.append(kwargs)
        return iter(self.pages)


class FakeAccountClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.paginator = FakePaginator(pages)
        self.paginator_operations: list[str] = []

    def get_paginator(self, operation_name: str) -> FakePaginator:
        self.paginator_operations.append(operation_name)
        return self.paginator


class FakeSourceSession:
    def __init__(self, client: FakeAccountClient) -> None:
        self.client_instance = client
        self.client_calls: list[tuple[str, Config]] = []

    def client(self, service_name: str, *, config: Config) -> FakeAccountClient:
        self.client_calls.append((service_name, config))
        return self.client_instance


def make_session(
    pages: list[dict[str, Any]],
) -> tuple[Session, FakeAccountClient, FakeSourceSession]:
    client = FakeAccountClient(pages)
    source = FakeSourceSession(client)
    return cast(Session, source), client, source


def test_list_enabled_regions_uses_pages_and_enabled_statuses() -> None:
    session, client, _ = make_session(
        [
            {
                "Regions": [
                    {
                        "RegionName": "eu-west-1",
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                    },
                    {
                        "RegionName": "ap-southeast-2",
                        "RegionOptStatus": "ENABLED",
                    },
                ]
            },
            {"Regions": [], "NextToken": "still-more"},
            {
                "Regions": [
                    {
                        "RegionName": "us-east-1",
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                    }
                ]
            },
        ]
    )

    regions = list_enabled_regions(session=session)

    assert regions == ["eu-west-1", "ap-southeast-2", "us-east-1"]
    assert client.paginator_operations == ["list_regions"]
    assert client.paginator.paginate_calls == [
        {
            "RegionOptStatusContains": ["ENABLED", "ENABLED_BY_DEFAULT"],
        }
    ]


def test_list_enabled_regions_excludes_requested_names() -> None:
    session, _, _ = make_session(
        [
            {
                "Regions": [
                    {"RegionName": "eu-west-1"},
                    {"RegionName": "us-east-1"},
                ]
            }
        ]
    )

    regions = list_enabled_regions(
        session=session,
        exclude_regions=["us-east-1"],
    )

    assert regions == ["eu-west-1"]


def test_list_enabled_regions_rejects_response_without_name() -> None:
    session, _, _ = make_session([{"Regions": [{"RegionOptStatus": "ENABLED"}]}])

    with pytest.raises(RuntimeError, match="RegionName"):
        list_enabled_regions(session=session)


def test_list_enabled_regions_rejects_non_string_region_name() -> None:
    session, _, _ = make_session(
        [{"Regions": [{"RegionName": 1, "RegionOptStatus": "ENABLED"}]}]
    )

    with pytest.raises(RuntimeError, match="non-string RegionName"):
        list_enabled_regions(session=session)


def test_list_enabled_regions_configures_account_client() -> None:
    session, _, source = make_session([{"Regions": []}])

    list_enabled_regions(session=session)

    service_name, config = source.client_calls[0]
    assert service_name == "account"
    assert config.retries == {
        "mode": "standard",
        "total_max_attempts": 3,
    }
