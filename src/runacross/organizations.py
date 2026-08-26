from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Iterable
from typing import Any, Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .exceptions import ConfigError
from .models import Account, AccountInput, coerce_accounts, coerce_limit
from .sts import build_client_config

logger = logging.getLogger(__name__)

_ORGANIZATION_ID_PATTERN = re.compile(r"o-[a-z0-9]{10,32}\Z")
_PARENT_ID_PATTERN = re.compile(
    r"(?:r-[0-9a-z]{4,32}|ou-[0-9a-z]{4,32}-[0-9a-z]{8,32})\Z"
)


class _Paginator(Protocol):
    def paginate(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Return all Organizations response pages."""


class _DescribeOrganizationsClient(Protocol):
    def describe_organization(self) -> dict[str, Any]:
        """Describe the caller's AWS Organization."""


class _OrganizationsClient(_DescribeOrganizationsClient, Protocol):
    def get_paginator(self, operation_name: str) -> _Paginator:
        """Create a paginator for an Organizations operation."""


def list_accounts(
    *,
    organization_id: str | None = None,
    parent_id: str | None = None,
    include_nested: bool = True,
    session: Session | None = None,
    botocore_config: Config | None = None,
    exclude_accounts: Iterable[AccountInput] = (),
    limit: int | None = None,
) -> list[Account]:
    """List active accounts from the caller's AWS Organization.

    With ``parent_id``, list accounts under that root or OU. Nested OUs are
    included by default. Without ``parent_id``, list the whole organization.
    """

    _validate_organization_id(organization_id)
    _validate_parent_id(parent_id)
    if not isinstance(include_nested, bool):
        raise TypeError("include_nested must be a bool")
    excluded_ids = {account.id for account in coerce_accounts(exclude_accounts)}
    max_accounts = coerce_limit(limit)

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
            raise ConfigError(
                "organization_id does not match the organization available "
                f"to the source credentials: expected {organization_id}, "
                f"got {actual_id}"
            )

    if parent_id is None:
        accounts = _list_organization_accounts(
            client,
            excluded_ids=excluded_ids,
            max_accounts=max_accounts,
        )
    else:
        accounts = _list_accounts_under_parent(
            client,
            parent_id,
            include_nested=include_nested,
            excluded_ids=excluded_ids,
            max_accounts=max_accounts,
        )

    logger.debug("Discovered %d active organization accounts", len(accounts))
    return accounts


def _list_organization_accounts(
    client: _OrganizationsClient,
    *,
    excluded_ids: set[str],
    max_accounts: int | None,
) -> list[Account]:
    accounts: list[Account] = []
    for page in client.get_paginator("list_accounts").paginate():
        if _extend_accounts(
            accounts,
            page.get("Accounts", []),
            excluded_ids=excluded_ids,
            max_accounts=max_accounts,
        ):
            return accounts
    return accounts


def _list_accounts_under_parent(
    client: _OrganizationsClient,
    parent_id: str,
    *,
    include_nested: bool,
    excluded_ids: set[str],
    max_accounts: int | None,
) -> list[Account]:
    accounts: list[Account] = []
    visited: set[str] = set()
    queue: deque[str] = deque([parent_id])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        for page in client.get_paginator("list_accounts_for_parent").paginate(
            ParentId=current
        ):
            if _extend_accounts(
                accounts,
                page.get("Accounts", []),
                excluded_ids=excluded_ids,
                max_accounts=max_accounts,
            ):
                return accounts

        if not include_nested:
            continue
        for page in client.get_paginator(
            "list_organizational_units_for_parent"
        ).paginate(ParentId=current):
            for item in page.get("OrganizationalUnits", []):
                child_id = item.get("Id")
                if not isinstance(child_id, str) or not child_id:
                    raise ConfigError(
                        "AWS Organizations returned an organizational unit "
                        "without a string Id"
                    )
                if child_id not in visited:
                    queue.append(child_id)

    return accounts


def _extend_accounts(
    accounts: list[Account],
    items: Any,
    *,
    excluded_ids: set[str],
    max_accounts: int | None,
) -> bool:
    for item in items:
        account = _account_from_organization_item(item)
        if account is None:
            continue
        if account.id in excluded_ids:
            logger.debug("Excluded organization account %s", account.id)
            continue
        accounts.append(account)
        if max_accounts is not None and len(accounts) >= max_accounts:
            logger.debug(
                "Reached account limit %d while listing organization accounts",
                max_accounts,
            )
            return True
    return False


def _account_from_organization_item(item: Any) -> Account | None:
    state = item.get("State")
    if state is None:
        raise ConfigError(
            "AWS Organizations did not return Account.State; "
            "use a Boto3 version released after September 9, 2025"
        )
    if state != "ACTIVE":
        return None

    account_id = item.get("Id")
    if account_id is None:
        raise ConfigError("AWS Organizations returned an account without an Id")
    return Account(
        id=account_id,
        name=item.get("Name"),
        email=item.get("Email"),
    )


def _validate_organization_id(organization_id: str | None) -> None:
    if organization_id is None:
        return
    if not isinstance(organization_id, str):
        raise TypeError("organization_id must be a string or None")
    if _ORGANIZATION_ID_PATTERN.fullmatch(organization_id) is None:
        raise ConfigError(
            "organization_id must start with 'o-' followed by "
            "10-32 lowercase letters or digits"
        )


def _validate_parent_id(parent_id: str | None) -> None:
    if parent_id is None:
        return
    if not isinstance(parent_id, str):
        raise TypeError("parent_id must be a string or None")
    if _PARENT_ID_PATTERN.fullmatch(parent_id) is None:
        raise ConfigError(
            "parent_id must be a root ID (r-...) or an organizational unit ID (ou-...)"
        )


def _get_organization_id(client: _DescribeOrganizationsClient) -> str:
    response = client.describe_organization()
    try:
        organization_id = response["Organization"]["Id"]
    except (KeyError, TypeError) as error:
        raise ConfigError(
            "AWS Organizations returned a response without Organization.Id"
        ) from error
    if not isinstance(organization_id, str):
        raise ConfigError("AWS Organizations returned a non-string Organization.Id")
    return organization_id
