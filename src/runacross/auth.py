from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .models import Account
from .sts import (
    StsClient,
    assume_role_session,
    build_client_config,
    copy_session,
    validate_assume_role_options,
)

_PROFILE_PATTERN_FIELDS = frozenset({"account_id", "name"})
_DEFAULT_ROLE_SESSION_NAME = "runacross"


class BoundAuth(Protocol):
    """An authentication strategy ready to create per-account Sessions."""

    def session_for(self, account: Account, *, region: str | None = None) -> Session:
        """Return an authenticated Session for one account."""

    def reporting_region(self) -> str | None:
        """A Region used when a failure has no target Region yet."""


class Auth(Protocol):
    """How RunAcross obtains a Boto3 Session for each account."""

    def bind(
        self,
        *,
        max_workers: int,
        botocore_config: Config | None,
    ) -> BoundAuth:
        """Prepare any shared clients before concurrent work starts."""


@dataclass(frozen=True)
class Role:
    """Authenticate by assuming an IAM role in each target account."""

    name: str
    session_name: str = _DEFAULT_ROLE_SESSION_NAME
    external_id: str | None = None
    duration_seconds: int | None = None
    source_session: Session | None = None

    def __post_init__(self) -> None:
        validate_assume_role_options(
            role_name=self.name,
            role_session_name=self.session_name,
            external_id=self.external_id,
            duration_seconds=self.duration_seconds,
        )

    def bind(
        self,
        *,
        max_workers: int,
        botocore_config: Config | None,
    ) -> BoundRole:
        """Create the shared STS client used to assume the role."""

        session = (
            self.source_session if self.source_session is not None else boto3.Session()
        )
        source_region = session.region_name
        if not source_region:
            raise ValueError(
                "source session must have a region; set AWS_DEFAULT_REGION, "
                "a profile region, or pass a Session with region_name"
            )
        sts_client = cast(
            StsClient,
            session.client(
                "sts",
                config=build_client_config(
                    max_pool_connections=max_workers,
                    user_config=botocore_config,
                ),
            ),
        )
        return BoundRole(
            role=self,
            sts_client=sts_client,
            source_region=source_region,
        )


class BoundRole:
    """Assume the configured role once per account and copy Sessions by Region."""

    def __init__(
        self,
        role: Role,
        sts_client: StsClient,
        source_region: str,
    ) -> None:
        self._role = role
        self._sts_client = sts_client
        self._source_region = source_region
        self._guard = threading.Lock()
        self._account_locks: dict[str, threading.Lock] = {}
        self._base_sessions: dict[str, Session] = {}

    def reporting_region(self) -> str | None:
        return self._source_region

    def session_for(self, account: Account, *, region: str | None = None) -> Session:
        region_name = region or self._source_region
        return copy_session(self._base_session(account), region_name)

    def _base_session(self, account: Account) -> Session:
        with self._guard:
            account_lock = self._account_locks.get(account.id)
            if account_lock is None:
                account_lock = threading.Lock()
                self._account_locks[account.id] = account_lock
        with account_lock:
            cached = self._base_sessions.get(account.id)
            if cached is not None:
                return cached
            session = assume_role_session(
                self._sts_client,
                account,
                role_name=self._role.name,
                role_session_name=self._role.session_name,
                external_id=self._role.external_id,
                duration_seconds=self._role.duration_seconds,
                region_name=self._source_region,
            )
            self._base_sessions[account.id] = session
            return session


@dataclass(frozen=True)
class Profile:
    """Authenticate with named AWS CLI / Identity Center profiles."""

    pattern: str | None = None
    mapping: Mapping[str, str] | None = None
    resolver: Callable[[Account], str] | None = None

    def __post_init__(self) -> None:
        selected = [
            name
            for name, value in (
                ("pattern", self.pattern),
                ("mapping", self.mapping),
                ("resolver", self.resolver),
            )
            if value is not None
        ]
        if len(selected) != 1:
            raise ValueError(
                "Profile requires exactly one of pattern, mapping, or resolver"
            )
        if self.pattern is not None:
            if not isinstance(self.pattern, str) or not self.pattern:
                raise TypeError("pattern must be a non-empty string")
            fields = {
                field_name
                for _, field_name, _, _ in Formatter().parse(self.pattern)
                if field_name is not None
            }
            unknown = fields - _PROFILE_PATTERN_FIELDS
            if unknown:
                unknown_list = ", ".join(sorted(unknown))
                raise ValueError(
                    "profile pattern placeholders must be account_id or name, "
                    f"not {unknown_list}"
                )
            return
        if self.resolver is not None:
            if not callable(self.resolver):
                raise TypeError("resolver must be callable")
            return
        if not isinstance(self.mapping, Mapping):
            raise TypeError("mapping must be a mapping of account IDs to profile names")
        normalized: dict[str, str] = {}
        for account_id, profile_name in self.mapping.items():
            if not isinstance(account_id, str):
                raise TypeError("mapping keys must be account ID strings")
            Account(id=account_id)
            if not isinstance(profile_name, str) or not profile_name:
                raise ValueError(
                    f"profile name for account {account_id} must be a non-empty string"
                )
            normalized[account_id] = profile_name
        object.__setattr__(self, "mapping", normalized)

    def bind(
        self,
        *,
        max_workers: int,
        botocore_config: Config | None,
    ) -> BoundProfile:
        """Profiles do not create shared AWS clients."""

        del max_workers, botocore_config
        return BoundProfile(self)

    def profile_name(self, account: Account) -> str:
        """Resolve the AWS profile name for one account."""

        if self.pattern is not None:
            if (
                "name"
                in {
                    field_name
                    for _, field_name, _, _ in Formatter().parse(self.pattern)
                    if field_name is not None
                }
                and account.name is None
            ):
                raise ValueError(
                    f"profile pattern uses {{name}} but account {account.id} has no name"
                )
            name = self.pattern.format(
                account_id=account.id,
                name=account.name or "",
            )
        elif self.mapping is not None:
            try:
                name = self.mapping[account.id]
            except KeyError as error:
                raise KeyError(
                    f"Profile mapping has no entry for account {account.id}"
                ) from error
        else:
            assert self.resolver is not None
            name = self.resolver(account)
        if not isinstance(name, str) or not name:
            raise ValueError("resolved profile name must be a non-empty string")
        return name


class BoundProfile:
    """Create a Boto3 Session from a named local profile."""

    def __init__(self, profile: Profile) -> None:
        self._profile = profile

    def reporting_region(self) -> str | None:
        return None

    def session_for(self, account: Account, *, region: str | None = None) -> Session:
        profile_name = self._profile.profile_name(account)
        session = cast(
            Session,
            boto3.Session(profile_name=profile_name, region_name=region),
        )
        if not session.region_name:
            raise ValueError(
                f"profile {profile_name!r} must have a region; set it in the AWS "
                "config, pass regions to map_account_regions, or set AWS_DEFAULT_REGION"
            )
        return session


def resolve_auth(
    *,
    auth: Auth | None,
    role_name: str | None,
    role_session_name: str,
    external_id: str | None,
    duration_seconds: int | None,
    source_session: Session | None,
) -> Auth:
    """Accept either an auth object or the 0.1 role_name shortcut."""

    role_kwargs_used = (
        role_name is not None
        or role_session_name != _DEFAULT_ROLE_SESSION_NAME
        or external_id is not None
        or duration_seconds is not None
        or source_session is not None
    )
    if auth is not None:
        if role_kwargs_used:
            raise TypeError(
                "pass auth=Role(...) or auth=Profile(...); do not combine auth "
                "with role_name, role_session_name, external_id, duration_seconds, "
                "or source_session"
            )
        bind = getattr(auth, "bind", None)
        if not callable(bind):
            raise TypeError("auth must be a Role or Profile")
        return auth
    if role_name is None:
        raise TypeError("auth or role_name is required")
    return Role(
        name=role_name,
        session_name=role_session_name,
        external_id=external_id,
        duration_seconds=duration_seconds,
        source_session=source_session,
    )
