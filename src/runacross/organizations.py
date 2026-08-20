from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any, Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .models import Account, AccountInput, coerce_accounts
from .sts import build_client_config

logger = logging.getLogger(__name__)

_ORGANIZATION_ID_PATTERN = re.compile(r"o-[a-z0-9]{10,32}\Z")


class _Paginator(Protocol):
    def paginate(self) -> Iterable[dict[str, Any]]:
        """Return all Organizations response pages."""


class _OrganizationsClient(Protocol):
    def describe_organization(self) -> dict[str, Any]:
        """Describe the caller's AWS Organization."""

    def get_paginator(self, operation_name: str) -> _Paginator:
        """Create a paginator for an Organizations operation."""


def list_accounts(
    *,
    organization_id: str | None = None,
    session: Session | None = None,
    botocore_config: Config | None = None,
    exclude_accounts: Iterable[AccountInput] = (),
) -> list[Account]:
    """List active accounts from the caller's AWS Organization."""

    _validate_organization_id(organization_id)
    excluded_ids = {account.id for account in coerce_accounts(exclude_accounts)}

    source_session = session if session is not None else boto3.Session()
    client = cast(
        _OrganizationsClient,
        source_session.client(
            "organizations",
            config=build_client_config(
                max_pool_connections=10,
                user_config=botocore_config,
            ),
        ),
    )

    if organization_id is not None:
        actual_id = _get_organization_id(client)
        if actual_id != organization_id:
            raise ValueError(
                "organization_id does not match the organization available "
                f"to the source credentials: expected {organization_id}, "
                f"got {actual_id}"
            )

    accounts: list[Account] = []
    paginator = client.get_paginator("list_accounts")
    for page in paginator.paginate():
        for item in page.get("Accounts", []):
            state = item.get("State")
            if state is None:
                raise RuntimeError(
                    "AWS Organizations did not return Account.State; "
                    "use a Boto3 version released after September 9, 2025"
                )
            if state != "ACTIVE":
                continue

            account_id = item.get("Id")
            if account_id is None:
                raise RuntimeError(
                    "AWS Organizations returned an account without an Id"
                )
            if account_id in excluded_ids:
                logger.debug("Excluded organization account %s", account_id)
                continue

            accounts.append(
                Account(
                    id=account_id,
                    name=item.get("Name"),
                    email=item.get("Email"),
                )
            )

    logger.debug("Discovered %d active organization accounts", len(accounts))
    return accounts


def _validate_organization_id(organization_id: str | None) -> None:
    if organization_id is None:
        return
    if not isinstance(organization_id, str):
        raise TypeError("organization_id must be a string or None")
    if _ORGANIZATION_ID_PATTERN.fullmatch(organization_id) is None:
        raise ValueError(
            "organization_id must start with 'o-' followed by "
            "10-32 lowercase letters or digits"
        )


def _get_organization_id(client: _OrganizationsClient) -> str:
    response = client.describe_organization()
    try:
        organization_id = response["Organization"]["Id"]
    except (KeyError, TypeError) as error:
        raise RuntimeError(
            "AWS Organizations returned a response without Organization.Id"
        ) from error
    if not isinstance(organization_id, str):
        raise RuntimeError("AWS Organizations returned a non-string Organization.Id")
    return organization_id
