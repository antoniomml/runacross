from __future__ import annotations

from typing import Any

import pytest
from botocore.config import Config

from runacross import Account
from runacross.sts import (
    assume_role_session,
    build_client_config,
    build_role_arn,
    copy_session,
    validate_assume_role_options,
)


class FakeMeta:
    def __init__(self, partition: str = "aws") -> None:
        self.partition = partition


class RecordingStsClient:
    def __init__(self, partition: str = "aws") -> None:
        self.meta = FakeMeta(partition)
        self.requests: list[dict[str, Any]] = []

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "temporary-access-key",
                "SecretAccessKey": "temporary-secret-key",
                "SessionToken": "temporary-session-token",
            }
        }


def test_build_role_arn_supports_partitions_and_role_paths() -> None:
    arn = build_role_arn(
        Account(id="123456789012"),
        "security/SecurityAuditRole",
        "aws-us-gov",
    )

    assert arn == "arn:aws-us-gov:iam::123456789012:role/security/SecurityAuditRole"


def test_assume_role_sends_expected_parameters_and_creates_session() -> None:
    client = RecordingStsClient()

    session = assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id="shared-external-id",
        duration_seconds=None,
        region_name="eu-west-1",
    )

    assert client.requests == [
        {
            "RoleArn": "arn:aws:iam::123456789012:role/SecurityAuditRole",
            "RoleSessionName": "runacross",
            "ExternalId": "shared-external-id",
        }
    ]
    assert session.region_name == "eu-west-1"
    credentials = session.get_credentials()
    assert credentials is not None
    frozen = credentials.get_frozen_credentials()
    assert frozen.access_key == "temporary-access-key"
    assert frozen.secret_key == "temporary-secret-key"
    assert frozen.token == "temporary-session-token"


def test_copy_session_uses_the_same_credentials_in_a_new_region() -> None:
    client = RecordingStsClient()
    session = assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=None,
        region_name="eu-west-1",
    )

    copied = copy_session(session, "us-east-1")
    credentials = copied.get_credentials()
    assert credentials is not None
    frozen = credentials.get_frozen_credentials()

    assert copied is not session
    assert copied.region_name == "us-east-1"
    assert frozen.access_key == "temporary-access-key"
    assert frozen.secret_key == "temporary-secret-key"
    assert frozen.token == "temporary-session-token"


def test_copy_session_rejects_a_session_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingStsClient()
    session = assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=None,
        region_name="eu-west-1",
    )
    monkeypatch.setattr(session, "get_credentials", lambda: None)

    with pytest.raises(RuntimeError, match="no credentials"):
        copy_session(session, "us-east-1")


def test_assume_role_omits_external_id_when_not_provided() -> None:
    client = RecordingStsClient()

    assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=None,
        region_name=None,
    )

    assert "ExternalId" not in client.requests[0]


@pytest.mark.parametrize(
    "role_session_name",
    ["a", "contains spaces", "x" * 65, "invalid!"],
)
def test_validate_assume_role_options_rejects_invalid_session_names(
    role_session_name: str,
) -> None:
    with pytest.raises(ValueError, match="role_session_name"):
        validate_assume_role_options(
            role_name="SecurityAuditRole",
            role_session_name=role_session_name,
            external_id=None,
            duration_seconds=None,
        )


@pytest.mark.parametrize(
    "role_name",
    [
        "",
        "/Role",
        "Role/",
        "path//Role",
        "A Role",
        "Role!",
        "Role:Admin",
        "x" * 65,
    ],
)
def test_validate_assume_role_options_rejects_invalid_role_names(
    role_name: str,
) -> None:
    with pytest.raises(ValueError, match="role_name"):
        validate_assume_role_options(
            role_name=role_name,
            role_session_name="runacross",
            external_id=None,
            duration_seconds=None,
        )


def test_validate_assume_role_options_rejects_invalid_external_id() -> None:
    with pytest.raises(ValueError, match="external_id"):
        validate_assume_role_options(
            role_name="SecurityAuditRole",
            role_session_name="runacross",
            external_id="contains spaces",
            duration_seconds=None,
        )


def test_build_client_config_uses_standard_retries_and_worker_pool() -> None:
    config = build_client_config(max_pool_connections=25, user_config=None)

    assert config.retries == {
        "mode": "standard",
        "total_max_attempts": 3,
    }
    assert config.max_pool_connections == 25


def test_user_client_config_takes_precedence() -> None:
    user_config = Config(
        retries={
            "mode": "adaptive",
            "total_max_attempts": 7,
        },
        max_pool_connections=50,
    )

    config = build_client_config(
        max_pool_connections=25,
        user_config=user_config,
    )

    assert config.retries == {
        "mode": "adaptive",
        "total_max_attempts": 7,
    }
    assert config.max_pool_connections == 50


def test_assume_role_sends_duration_seconds_when_provided() -> None:
    client = RecordingStsClient()

    assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=900,
        region_name="eu-west-1",
    )

    assert client.requests[0]["DurationSeconds"] == 900


def test_assume_role_omits_duration_seconds_when_not_provided() -> None:
    client = RecordingStsClient()

    assume_role_session(
        client,
        Account(id="123456789012"),
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=None,
        region_name="eu-west-1",
    )

    assert "DurationSeconds" not in client.requests[0]


@pytest.mark.parametrize("duration_seconds", [899, 43201])
def test_validate_assume_role_options_rejects_duration_out_of_range(
    duration_seconds: int,
) -> None:
    with pytest.raises(ValueError, match="duration_seconds"):
        validate_assume_role_options(
            role_name="SecurityAuditRole",
            role_session_name="runacross",
            external_id=None,
            duration_seconds=duration_seconds,
        )


def test_validate_assume_role_options_rejects_boolean_duration() -> None:
    with pytest.raises(TypeError, match="duration_seconds"):
        validate_assume_role_options(
            role_name="SecurityAuditRole",
            role_session_name="runacross",
            external_id=None,
            duration_seconds=True,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("duration_seconds", [900, 3600, 43200])
def test_validate_assume_role_options_accepts_duration_bounds(
    duration_seconds: int,
) -> None:
    validate_assume_role_options(
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=duration_seconds,
    )
