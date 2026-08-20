from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import pytest
from boto3.session import Session
from botocore.config import Config

from runacross import Account
from runacross.organizations import list_accounts


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.paginate_calls = 0

    def paginate(self) -> Iterable[dict[str, Any]]:
        self.paginate_calls += 1
        return iter(self.pages)


class FakeOrganizationsClient:
    def __init__(
        self,
        pages: list[dict[str, Any]],
        *,
        organization_id: str = "o-exampleorgid",
    ) -> None:
        self.paginator = FakePaginator(pages)
        self.organization_id = organization_id
        self.describe_calls = 0
        self.paginator_operations: list[str] = []

    def describe_organization(self) -> dict[str, Any]:
        self.describe_calls += 1
        return {"Organization": {"Id": self.organization_id}}

    def get_paginator(self, operation_name: str) -> FakePaginator:
        self.paginator_operations.append(operation_name)
        return self.paginator


class FakeSourceSession:
    def __init__(self, client: FakeOrganizationsClient) -> None:
        self.client_instance = client
        self.client_calls: list[tuple[str, Config]] = []

    def client(
        self,
        service_name: str,
        *,
        config: Config,
    ) -> FakeOrganizationsClient:
        self.client_calls.append((service_name, config))
        return self.client_instance


def make_session(
    pages: list[dict[str, Any]],
    *,
    organization_id: str = "o-exampleorgid",
) -> tuple[Session, FakeOrganizationsClient, FakeSourceSession]:
    client = FakeOrganizationsClient(pages, organization_id=organization_id)
    source = FakeSourceSession(client)
    return cast(Session, source), client, source


def active_account(
    account_id: str,
    *,
    name: str | None = None,
    email: str | None = None,
) -> dict[str, str]:
    account = {
        "Id": account_id,
        "State": "ACTIVE",
    }
    if name is not None:
        account["Name"] = name
    if email is not None:
        account["Email"] = email
    return account


def test_list_accounts_uses_all_pages_and_filters_active_accounts() -> None:
    session, client, _ = make_session(
        [
            {
                "Accounts": [
                    active_account(
                        "111111111111",
                        name="Production",
                        email="prod@example.com",
                    ),
                    {
                        "Id": "222222222222",
                        "Name": "Suspended",
                        "State": "SUSPENDED",
                    },
                ],
                "NextToken": "next",
            },
            {"Accounts": [], "NextToken": "still-more"},
            {
                "Accounts": [
                    active_account("333333333333", name="Development"),
                ]
            },
        ]
    )

    accounts = list_accounts(session=session)

    assert accounts == [
        Account(
            id="111111111111",
            name="Production",
            email="prod@example.com",
        ),
        Account(id="333333333333", name="Development"),
    ]
    assert client.paginator_operations == ["list_accounts"]
    assert client.paginator.paginate_calls == 1
    assert client.describe_calls == 0


def test_list_accounts_validates_expected_organization_id() -> None:
    session, client, _ = make_session([{"Accounts": [active_account("111111111111")]}])

    accounts = list_accounts(
        organization_id="o-exampleorgid",
        session=session,
    )

    assert accounts == [Account(id="111111111111")]
    assert client.describe_calls == 1


def test_list_accounts_rejects_organization_mismatch_before_pagination() -> None:
    session, client, _ = make_session(
        [{"Accounts": [active_account("111111111111")]}],
        organization_id="o-otherorgid1",
    )

    with pytest.raises(ValueError, match="does not match"):
        list_accounts(
            organization_id="o-exampleorgid",
            session=session,
        )

    assert client.paginator_operations == []


def test_list_accounts_excludes_requested_accounts() -> None:
    session, _, _ = make_session(
        [
            {
                "Accounts": [
                    active_account("111111111111"),
                    active_account("222222222222"),
                    active_account("333333333333"),
                ]
            }
        ]
    )

    accounts = list_accounts(
        session=session,
        exclude_accounts=[
            "111111111111",
            Account(id="333333333333"),
        ],
    )

    assert accounts == [Account(id="222222222222")]


def test_list_accounts_rejects_response_without_state() -> None:
    session, _, _ = make_session(
        [{"Accounts": [{"Id": "111111111111", "Status": "ACTIVE"}]}]
    )

    with pytest.raises(RuntimeError, match=r"Account\.State"):
        list_accounts(session=session)


@pytest.mark.parametrize(
    "organization_id",
    ["exampleorgid", "o-short", "o-UPPERCASE123", "o-invalid_symbol"],
)
def test_list_accounts_rejects_invalid_organization_ids(
    organization_id: str,
) -> None:
    session, _, source = make_session([])

    with pytest.raises(ValueError, match="organization_id"):
        list_accounts(
            organization_id=organization_id,
            session=session,
        )

    assert source.client_calls == []


def test_list_accounts_configures_organizations_client() -> None:
    session, _, source = make_session([{"Accounts": []}])

    list_accounts(session=session)

    service_name, config = source.client_calls[0]
    assert service_name == "organizations"
    assert config.retries == {
        "mode": "standard",
        "total_max_attempts": 3,
    }
