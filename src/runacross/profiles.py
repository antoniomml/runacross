from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from string import Formatter
from typing import Any, Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config
from botocore.session import Session as BotocoreSession

from .auth import _resolve_session_credentials
from .exceptions import ConfigError
from .models import Account, AccountInput, coerce_accounts, coerce_limit
from .organizations import _get_organization_id, _validate_organization_id
from .sts import build_client_config

logger = logging.getLogger(__name__)


class _OrganizationsClient(Protocol):
    def describe_organization(self) -> dict[str, Any]:
        """Describe the caller's AWS Organization."""


def list_accounts(
    *,
    pattern: str,
    sso_session: str,
    organization_id: str | None = None,
    organization_profile: str | None = None,
    botocore_config: Config | None = None,
    exclude_accounts: Iterable[AccountInput] = (),
    limit: int | None = None,
) -> list[Account]:
    """Discover accounts from local Identity Center profiles in one SSO session."""

    profile_pattern = _compile_profile_pattern(pattern)
    _validate_sso_session(sso_session)
    _validate_organization_options(organization_id, organization_profile)
    excluded_ids = {account.id for account in coerce_accounts(exclude_accounts)}
    max_accounts = coerce_limit(limit)

    full_config = cast(dict[str, Any], BotocoreSession().full_config)
    profiles = _config_section(full_config, "profiles")
    sso_sessions = _config_section(full_config, "sso_sessions")
    if sso_session not in sso_sessions:
        raise ConfigError(
            f"sso_session {sso_session!r} was not found in the shared AWS config"
        )

    accounts: list[Account] = []
    for profile_name, raw_profile in profiles.items():
        if not isinstance(raw_profile, Mapping):
            continue
        if raw_profile.get("sso_session") != sso_session:
            continue

        match = profile_pattern.fullmatch(profile_name)
        if match is None:
            continue

        configured_account_id = raw_profile.get("sso_account_id")
        if not isinstance(configured_account_id, str):
            raise ConfigError(
                f"profile {profile_name!r} must define a string sso_account_id"
            )
        matched_account_id = match.group("account_id")
        if configured_account_id != matched_account_id:
            raise ConfigError(
                f"profile {profile_name!r} identifies account {matched_account_id} "
                f"in its name but configures sso_account_id {configured_account_id}"
            )
        try:
            account = Account(id=configured_account_id)
        except (TypeError, ValueError) as error:
            raise ConfigError(
                f"profile {profile_name!r} has invalid sso_account_id "
                f"{configured_account_id!r}"
            ) from error
        if account.id in excluded_ids:
            logger.debug("Excluded profile account %s", account.id)
            continue
        accounts.append(account)
        if max_accounts is not None and len(accounts) >= max_accounts:
            break

    if organization_profile is not None:
        _validate_organization_profile(
            profiles,
            sso_session=sso_session,
            organization_id=cast(str, organization_id),
            organization_profile=organization_profile,
            botocore_config=botocore_config,
        )

    logger.debug(
        "Discovered %d accounts from SSO session %s",
        len(accounts),
        sso_session,
    )
    return accounts


def _compile_profile_pattern(pattern: str) -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a non-empty string")
    if not pattern:
        raise ConfigError("pattern must be a non-empty string")
    try:
        parsed = list(Formatter().parse(pattern))
    except ValueError as error:
        raise ConfigError("pattern must be a valid format string") from error

    expression: list[str] = []
    account_fields = 0
    for literal, field_name, format_spec, conversion in parsed:
        expression.append(re.escape(literal))
        if field_name is None:
            continue
        if field_name != "account_id":
            raise ConfigError(
                "profile discovery pattern placeholders must be account_id"
            )
        if format_spec or conversion:
            raise ConfigError(
                "account_id in a profile discovery pattern cannot use a format "
                "specification or conversion"
            )
        account_fields += 1
        expression.append(r"(?P<account_id>[0-9]{12})")

    if account_fields != 1:
        raise ConfigError(
            "profile discovery pattern must contain exactly one {account_id}"
        )
    return re.compile("".join(expression))


def _validate_sso_session(sso_session: str) -> None:
    if not isinstance(sso_session, str):
        raise TypeError("sso_session must be a non-empty string")
    if not sso_session:
        raise ConfigError("sso_session must be a non-empty string")


def _validate_organization_options(
    organization_id: str | None,
    organization_profile: str | None,
) -> None:
    _validate_organization_id(organization_id)
    if organization_profile is not None:
        if not isinstance(organization_profile, str):
            raise TypeError("organization_profile must be a non-empty string or None")
        if not organization_profile:
            raise ConfigError("organization_profile must be a non-empty string or None")
    if (organization_id is None) != (organization_profile is None):
        raise TypeError(
            "organization_id and organization_profile must be provided together"
        )


def _config_section(
    full_config: Mapping[str, Any],
    section_name: str,
) -> Mapping[str, Any]:
    section = full_config.get(section_name, {})
    if not isinstance(section, Mapping):
        raise ConfigError(
            f"Botocore returned a non-mapping {section_name!r} config section"
        )
    return section


def _validate_organization_profile(
    profiles: Mapping[str, Any],
    *,
    sso_session: str,
    organization_id: str,
    organization_profile: str,
    botocore_config: Config | None,
) -> None:
    raw_profile = profiles.get(organization_profile)
    if not isinstance(raw_profile, Mapping):
        raise ConfigError(
            f"organization_profile {organization_profile!r} was not found in the "
            "shared AWS config"
        )
    profile_sso_session = raw_profile.get("sso_session")
    if profile_sso_session != sso_session:
        raise ConfigError(
            f"organization_profile {organization_profile!r} uses sso_session "
            f"{profile_sso_session!r}, not {sso_session!r}"
        )

    session = cast(Session, boto3.Session(profile_name=organization_profile))
    if not session.region_name:
        raise ConfigError(
            f"organization profile {organization_profile!r} must have a region; "
            "set it in the AWS config or set AWS_DEFAULT_REGION"
        )
    _resolve_session_credentials(session, organization_profile)
    client = cast(
        _OrganizationsClient,
        session.client(
            "organizations",
            config=build_client_config(
                max_pool_connections=10,
                user_config=botocore_config,
            ),
        ),
    )
    actual_id = _get_organization_id(client)
    if actual_id != organization_id:
        raise ConfigError(
            "organization_id does not match the organization available to "
            f"organization_profile {organization_profile!r}: expected "
            f"{organization_id}, got {actual_id}"
        )
