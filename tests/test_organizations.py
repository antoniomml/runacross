from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import pytest
from boto3.session import Session
from botocore.config import Config

from runacross import Account, ConfigError
from runacross.organizations import list_accounts


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.paginate_calls = 0

    def paginate(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        self.paginate_calls += 1
        return iter(self.pages)


class FakeParentPaginator:
    def __init__(self, pages_by_parent: dict[str, list[dict[str, Any]]]) -> None:
        self.pages_by_parent = pages_by_parent
        self.paginate_kwargs: list[dict[str, Any]] = []

    def paginate(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        self.paginate_kwargs.append(kwargs)
        return iter(self.pages_by_parent.get(kwargs["ParentId"], []))


class FakeOrganizationsClient:
    def __init__(
        self,
        pages: list[dict[str, Any]] | None = None,
        *,
        organization_id: str = "o-exampleorgid",
        accounts_for_parent: dict[str, list[dict[str, Any]]] | None = None,
        organizational_units_for_parent: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.paginator = FakePaginator(pages or [])
        self.accounts_for_parent_paginator = FakeParentPaginator(
            accounts_for_parent or {}
        )
        self.organizational_units_for_parent_paginator = FakeParentPaginator(
            organizational_units_for_parent or {}
        )
        self.organization_id = organization_id
        self.describe_calls = 0
        self.paginator_operations: list[str] = []

    def describe_organization(self) -> dict[str, Any]:
        self.describe_calls += 1
        return {"Organization": {"Id": self.organization_id}}

    def get_paginator(self, operation_name: str) -> FakePaginator | FakeParentPaginator:
        self.paginator_operations.append(operation_name)
        if operation_name == "list_accounts":
            return self.paginator
        if operation_name == "list_accounts_for_parent":
            return self.accounts_for_parent_paginator
        if operation_name == "list_organizational_units_for_parent":
            return self.organizational_units_for_parent_paginator
        raise AssertionError(f"unexpected paginator {operation_name}")


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
    pages: list[dict[str, Any]] | None = None,
    *,
    organization_id: str = "o-exampleorgid",
    accounts_for_parent: dict[str, list[dict[str, Any]]] | None = None,
    organizational_units_for_parent: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[Session, FakeOrganizationsClient, FakeSourceSession]:
    client = FakeOrganizationsClient(
        pages,
        organization_id=organization_id,
        accounts_for_parent=accounts_for_parent,
        organizational_units_for_parent=organizational_units_for_parent,
    )
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

    with pytest.raises(ConfigError, match="does not match"):
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


def test_list_accounts_limit_stops_after_active_matches() -> None:
    session, _, _ = make_session(
        [
            {
                "Accounts": [
                    active_account("111111111111"),
                    {"Id": "222222222222", "State": "SUSPENDED"},
                    active_account("333333333333"),
                    active_account("444444444444"),
                ]
            }
        ]
    )

    accounts = list_accounts(session=session, limit=2)

    assert accounts == [
        Account(id="111111111111"),
        Account(id="333333333333"),
    ]


def test_list_accounts_rejects_response_without_state() -> None:
    session, _, _ = make_session(
        [{"Accounts": [{"Id": "111111111111", "Status": "ACTIVE"}]}]
    )

    with pytest.raises(ConfigError, match=r"Account\.State"):
        list_accounts(session=session)


@pytest.mark.parametrize(
    "organization_id",
    ["exampleorgid", "o-short", "o-UPPERCASE123", "o-invalid_symbol"],
)
def test_list_accounts_rejects_invalid_organization_ids(
    organization_id: str,
) -> None:
    session, _, source = make_session([])

    with pytest.raises(ConfigError, match="organization_id"):
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


WORKLOADS_OU = "ou-examp-workloads"
PROD_OU = "ou-examp-prodacct"
DEV_OU = "ou-examp-devacct1"


def parent_pages(
    *accounts: dict[str, str],
) -> list[dict[str, Any]]:
    return [{"Accounts": list(accounts)}]


def ou_pages(*ou_ids: str) -> list[dict[str, Any]]:
    return [{"OrganizationalUnits": [{"Id": ou_id} for ou_id in ou_ids]}]


def nested_ou_session() -> tuple[Session, FakeOrganizationsClient, FakeSourceSession]:
    return make_session(
        accounts_for_parent={
            WORKLOADS_OU: parent_pages(
                active_account("111111111111", name="Shared"),
                {"Id": "000000000000", "State": "SUSPENDED"},
            ),
            PROD_OU: parent_pages(active_account("222222222222", name="Production")),
            DEV_OU: parent_pages(active_account("333333333333", name="Development")),
        },
        organizational_units_for_parent={
            WORKLOADS_OU: ou_pages(PROD_OU, DEV_OU),
            PROD_OU: ou_pages(),
            DEV_OU: ou_pages(),
        },
    )


def test_list_accounts_under_parent_includes_nested_ous_by_default() -> None:
    session, client, _ = nested_ou_session()

    accounts = list_accounts(session=session, parent_id=WORKLOADS_OU)

    assert accounts == [
        Account(id="111111111111", name="Shared"),
        Account(id="222222222222", name="Production"),
        Account(id="333333333333", name="Development"),
    ]
    assert client.paginator.paginate_calls == 0
    assert client.paginator_operations == [
        "list_accounts_for_parent",
        "list_organizational_units_for_parent",
        "list_accounts_for_parent",
        "list_organizational_units_for_parent",
        "list_accounts_for_parent",
        "list_organizational_units_for_parent",
    ]
    assert [
        call["ParentId"]
        for call in client.accounts_for_parent_paginator.paginate_kwargs
    ] == [WORKLOADS_OU, PROD_OU, DEV_OU]


def test_list_accounts_under_parent_can_skip_nested_ous() -> None:
    session, client, _ = nested_ou_session()

    accounts = list_accounts(
        session=session,
        parent_id=WORKLOADS_OU,
        include_nested=False,
    )

    assert accounts == [Account(id="111111111111", name="Shared")]
    assert client.paginator_operations == ["list_accounts_for_parent"]
    assert client.organizational_units_for_parent_paginator.paginate_kwargs == []


def test_list_accounts_under_parent_applies_exclude_and_limit() -> None:
    session, _, _ = nested_ou_session()

    accounts = list_accounts(
        session=session,
        parent_id=WORKLOADS_OU,
        exclude_accounts=["111111111111"],
        limit=1,
    )

    assert accounts == [Account(id="222222222222", name="Production")]


def test_list_accounts_under_parent_does_not_loop_on_cycles() -> None:
    session, client, _ = make_session(
        accounts_for_parent={
            WORKLOADS_OU: parent_pages(active_account("111111111111")),
            PROD_OU: parent_pages(active_account("222222222222")),
        },
        organizational_units_for_parent={
            WORKLOADS_OU: ou_pages(PROD_OU, PROD_OU),
            PROD_OU: ou_pages(WORKLOADS_OU),
        },
    )

    accounts = list_accounts(session=session, parent_id=WORKLOADS_OU)

    assert accounts == [
        Account(id="111111111111"),
        Account(id="222222222222"),
    ]
    assert client.accounts_for_parent_paginator.paginate_kwargs == [
        {"ParentId": WORKLOADS_OU},
        {"ParentId": PROD_OU},
    ]


def test_list_accounts_rejects_organization_mismatch_before_parent_listing() -> None:
    session, client, _ = make_session(
        organization_id="o-otherorgid1",
        accounts_for_parent={
            WORKLOADS_OU: parent_pages(active_account("111111111111")),
        },
    )

    with pytest.raises(ConfigError, match="does not match"):
        list_accounts(
            organization_id="o-exampleorgid",
            parent_id=WORKLOADS_OU,
            session=session,
        )

    assert client.paginator_operations == []
    assert client.describe_calls == 1


@pytest.mark.parametrize(
    "parent_id",
    ["ou-short", "r-ab", "ou-EXAMP-workloads", "ou-examp-short", "root"],
)
def test_list_accounts_rejects_invalid_parent_ids(parent_id: str) -> None:
    session, _, source = make_session([])

    with pytest.raises(ConfigError, match="parent_id"):
        list_accounts(parent_id=parent_id, session=session)

    assert source.client_calls == []


def test_list_accounts_rejects_non_bool_include_nested() -> None:
    session, _, source = make_session([])

    with pytest.raises(TypeError, match="include_nested"):
        list_accounts(session=session, include_nested=1)  # type: ignore[arg-type]

    assert source.client_calls == []


def test_list_accounts_rejects_parent_response_without_ou_id() -> None:
    session, _, _ = make_session(
        accounts_for_parent={WORKLOADS_OU: parent_pages()},
        organizational_units_for_parent={
            WORKLOADS_OU: [{"OrganizationalUnits": [{"Name": "Production"}]}],
        },
    )

    with pytest.raises(ConfigError, match="organizational unit"):
        list_accounts(session=session, parent_id=WORKLOADS_OU)


def test_list_accounts_rejects_account_without_id() -> None:
    session, _, _ = make_session(
        [{"Accounts": [{"State": "ACTIVE", "Name": "Production"}]}]
    )

    with pytest.raises(ConfigError, match="without an Id"):
        list_accounts(session=session)


def test_list_accounts_rejects_non_string_parent_id() -> None:
    session, _, source = make_session([])

    with pytest.raises(TypeError, match="parent_id"):
        list_accounts(parent_id=1, session=session)  # type: ignore[arg-type]

    assert source.client_calls == []


def test_list_accounts_rejects_non_string_organization_id() -> None:
    session, _, source = make_session([])

    with pytest.raises(TypeError, match="organization_id"):
        list_accounts(organization_id=1, session=session)  # type: ignore[arg-type]

    assert source.client_calls == []


def test_list_accounts_rejects_describe_response_without_id() -> None:
    session, client, _ = make_session([{"Accounts": []}])
    client.describe_organization = lambda: {"Organization": {}}  # type: ignore[method-assign]

    with pytest.raises(ConfigError, match=r"Organization\.Id"):
        list_accounts(organization_id="o-exampleorgid", session=session)


def test_list_accounts_rejects_non_string_organization_response_id() -> None:
    session, client, _ = make_session([{"Accounts": []}])
    client.describe_organization = lambda: {"Organization": {"Id": 1}}  # type: ignore[method-assign]

    with pytest.raises(ConfigError, match=r"non-string Organization\.Id"):
        list_accounts(organization_id="o-exampleorgid", session=session)
