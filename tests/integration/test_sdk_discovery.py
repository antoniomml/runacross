from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from runacross import ConfigError
from runacross.organizations import list_accounts
from runacross.regions import list_enabled_regions


def account(account_id: str, state: str = "ACTIVE") -> dict[str, str]:
    return {
        "Id": account_id,
        "State": state,
        "Name": "synthetic",
        "Email": "test@example.com",
    }


def test_organizations_empty_pages_filters_and_early_limit(sdk_source: Any) -> None:
    session, clients = sdk_source
    with Stubber(clients["organizations"]) as stub:
        stub.add_response("list_accounts", {"Accounts": [], "NextToken": "page2"}, {})
        stub.add_response(
            "list_accounts",
            {
                "Accounts": [
                    account("111111111111", "SUSPENDED"),
                    account("222222222222"),
                ],
                "NextToken": "page3",
            },
            {"NextToken": "page2"},
        )
        stub.add_response(
            "list_accounts",
            {
                "Accounts": [
                    account("333333333333"),
                    account("444444444444"),
                ],
                "NextToken": "not-requested",
            },
            {"NextToken": "page3"},
        )
        accounts = list_accounts(
            session=session, exclude_accounts=["222222222222"], limit=1
        )
        stub.assert_no_pending_responses()
    assert [item.id for item in accounts] == ["333333333333"]
    assert accounts[0].email == "test@example.com"
    assert "test@example.com" not in repr(accounts[0])


def test_organizations_nested_ou_pagination_uses_correct_parent_ids(
    sdk_source: Any,
) -> None:
    session, clients = sdk_source
    with Stubber(clients["organizations"]) as stub:
        stub.add_response(
            "list_accounts_for_parent",
            {"Accounts": [], "NextToken": "accounts2"},
            {"ParentId": "r-abcd"},
        )
        stub.add_response(
            "list_accounts_for_parent",
            {"Accounts": [account("111111111111")]},
            {"ParentId": "r-abcd", "NextToken": "accounts2"},
        )
        stub.add_response(
            "list_organizational_units_for_parent",
            {"OrganizationalUnits": [], "NextToken": "ous2"},
            {"ParentId": "r-abcd"},
        )
        stub.add_response(
            "list_organizational_units_for_parent",
            {"OrganizationalUnits": [{"Id": "ou-abcd-12345678", "Name": "child"}]},
            {"ParentId": "r-abcd", "NextToken": "ous2"},
        )
        stub.add_response(
            "list_accounts_for_parent",
            {"Accounts": [account("222222222222")]},
            {"ParentId": "ou-abcd-12345678"},
        )
        stub.add_response(
            "list_organizational_units_for_parent",
            {"OrganizationalUnits": []},
            {"ParentId": "ou-abcd-12345678"},
        )
        accounts = list_accounts(session=session, parent_id="r-abcd")
        stub.assert_no_pending_responses()
    assert [item.id for item in accounts] == ["111111111111", "222222222222"]


def test_organization_guard_stops_before_listing_an_unexpected_organization(
    sdk_source: Any,
) -> None:
    session, clients = sdk_source
    with Stubber(clients["organizations"]) as stub:
        stub.add_response(
            "describe_organization", {"Organization": {"Id": "o-actualorgid"}}, {}
        )
        with pytest.raises(ConfigError, match="does not match"):
            list_accounts(session=session, organization_id="o-expectedorgid")
        stub.assert_no_pending_responses()


def test_sdk_discovery_errors_propagate_without_wrapping(sdk_source: Any) -> None:
    session, clients = sdk_source
    with Stubber(clients["organizations"]) as stub:
        stub.add_client_error(
            "list_accounts",
            "AccessDeniedException",
            "synthetic denial",
            expected_params={},
        )
        with pytest.raises(ClientError) as caught:
            list_accounts(session=session)
        stub.assert_no_pending_responses()
    assert caught.value.response["Error"]["Code"] == "AccessDeniedException"


def test_region_paginator_continues_after_empty_page_and_applies_exclusion(
    sdk_source: Any,
) -> None:
    session, clients = sdk_source
    params = {"RegionOptStatusContains": ["ENABLED", "ENABLED_BY_DEFAULT"]}
    with Stubber(clients["account"]) as stub:
        stub.add_response("list_regions", {"Regions": [], "NextToken": "page2"}, params)
        stub.add_response(
            "list_regions",
            {
                "Regions": [
                    {
                        "RegionName": "eu-west-1",
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                    },
                    {"RegionName": "ap-east-1", "RegionOptStatus": "ENABLED"},
                ]
            },
            {**params, "NextToken": "page2"},
        )
        regions = list_enabled_regions(session=session, exclude_regions=["ap-east-1"])
        stub.assert_no_pending_responses()
    assert regions == ["eu-west-1"]
