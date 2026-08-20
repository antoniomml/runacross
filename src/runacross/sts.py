from __future__ import annotations

import re
from typing import Any, Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .models import Account

_ROLE_SESSION_NAME_PATTERN = re.compile(r"[A-Za-z0-9_+=,.@-]{2,64}\Z")
_EXTERNAL_ID_PATTERN = re.compile(r"[A-Za-z0-9_+=,.@:/-]{2,1224}\Z")
_ROLE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_+=,.@-]{1,64}\Z")
_ROLE_PATH_PATTERN = re.compile(r"[\x21-\x7e]*\Z")


class _ClientMeta(Protocol):
    partition: str


class StsClient(Protocol):
    """The subset of an STS client used by RunAcross."""

    meta: _ClientMeta

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        """Call STS AssumeRole."""


def build_client_config(
    *,
    max_pool_connections: int,
    user_config: Config | None,
) -> Config:
    """Create the Botocore configuration for RunAcross-owned clients."""

    defaults = Config(
        retries={
            "mode": "standard",
            "total_max_attempts": 3,
        },
        max_pool_connections=max(10, max_pool_connections),
    )
    return defaults.merge(user_config) if user_config is not None else defaults


def validate_assume_role_options(
    *,
    role_name: str,
    role_session_name: str,
    external_id: str | None,
) -> None:
    """Validate global AssumeRole options before concurrent work starts."""

    if not isinstance(role_name, str):
        raise TypeError("role_name must be a string")
    if (
        not role_name
        or role_name.startswith("/")
        or role_name.endswith("/")
        or "//" in role_name
    ):
        raise ValueError("role_name must be a non-empty IAM role name or path")

    *path_parts, final_role_name = role_name.split("/")
    role_path = "/".join(path_parts)
    iam_path = f"/{role_path}/" if role_path else "/"
    if (
        _ROLE_NAME_PATTERN.fullmatch(final_role_name) is None
        or _ROLE_PATH_PATTERN.fullmatch(role_path) is None
        or len(iam_path) > 512
    ):
        raise ValueError(
            "role_name must contain a valid IAM path and a 1-64 character "
            "role name using letters, digits, or _+=,.@-"
        )

    if not isinstance(role_session_name, str):
        raise TypeError("role_session_name must be a string")
    if _ROLE_SESSION_NAME_PATTERN.fullmatch(role_session_name) is None:
        raise ValueError(
            "role_session_name must be 2-64 characters using "
            "letters, digits, or _+=,.@-"
        )

    if external_id is not None:
        if not isinstance(external_id, str):
            raise TypeError("external_id must be a string or None")
        if _EXTERNAL_ID_PATTERN.fullmatch(external_id) is None:
            raise ValueError(
                "external_id must be 2-1224 characters using "
                "letters, digits, or _+=,.@:/-"
            )


def build_role_arn(account: Account, role_name: str, partition: str) -> str:
    """Build an IAM role ARN for an account and AWS partition."""

    return f"arn:{partition}:iam::{account.id}:role/{role_name}"


def assume_role_session(
    sts_client: StsClient,
    account: Account,
    *,
    role_name: str,
    role_session_name: str,
    external_id: str | None,
    region_name: str | None,
) -> Session:
    """Assume a role and create a new Session for one account."""

    request: dict[str, Any] = {
        "RoleArn": build_role_arn(
            account,
            role_name,
            sts_client.meta.partition,
        ),
        "RoleSessionName": role_session_name,
    }
    if external_id is not None:
        request["ExternalId"] = external_id

    response = sts_client.assume_role(**request)
    credentials = response["Credentials"]

    return cast(
        Session,
        boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=region_name,
        ),
    )
