from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.credentials import CredentialResolver, SSOProvider
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from botocore.tokens import SSOTokenProvider

from runacross import ExecutionPhase, Profile, Role, map_account_regions, map_accounts


def role_response() -> dict[str, Any]:
    return {
        "Credentials": {
            "AccessKeyId": "ASIATEST000000000000",
            "SecretAccessKey": "s" * 40,
            "SessionToken": "synthetic-session-token",
            "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "AssumedRoleUser": {
            "AssumedRoleId": "AROAEXAMPLE:audit",
            "Arn": "arn:aws:sts::111111111111:assumed-role/audit/runacross",
        },
    }


def test_sts_request_and_credentials_reuse_across_regions(sdk_source: Any) -> None:
    source, clients = sdk_source
    sessions = []
    with Stubber(clients["sts"]) as stub:
        stub.add_response(
            "assume_role",
            role_response(),
            {
                "RoleArn": "arn:aws:iam::111111111111:role/team/audit",
                "RoleSessionName": "inventory",
                "ExternalId": "synthetic-external-id",
                "DurationSeconds": 900,
            },
        )

        def worker(session: Any, _account: Any, region: str) -> tuple[str, str]:
            sessions.append(session)
            credentials = session.get_credentials().get_frozen_credentials()
            assert credentials.token == "synthetic-session-token"
            assert session.region_name == region
            return region, credentials.access_key

        results = map_account_regions(
            worker,
            accounts=["111111111111"],
            regions=["eu-west-1", "us-east-1", "ap-southeast-2"],
            auth=Role(
                "team/audit",
                session_name="inventory",
                external_id="synthetic-external-id",
                duration_seconds=900,
                source_session=source,
            ),
            max_workers=3,
        )
        stub.assert_no_pending_responses()
    assert results.success_count == 3
    assert len({id(session) for session in sessions}) == 3
    assert [r.value[0] for r in results] == ["eu-west-1", "us-east-1", "ap-southeast-2"]


def test_sts_denial_remains_original_error_and_other_accounts_continue(
    sdk_source: Any,
) -> None:
    source, clients = sdk_source
    with Stubber(clients["sts"]) as stub:
        stub.add_client_error(
            "assume_role",
            "AccessDenied",
            "synthetic denial",
            http_status_code=403,
            expected_params={
                "RoleArn": "arn:aws:iam::222222222222:role/audit",
                "RoleSessionName": "runacross",
            },
        )
        stub.add_response(
            "assume_role",
            role_response(),
            {
                "RoleArn": "arn:aws:iam::111111111111:role/audit",
                "RoleSessionName": "runacross",
            },
        )
        results = map_accounts(
            lambda _session, account: account.id,
            accounts=["222222222222", "111111111111"],
            auth=Role("audit", source_session=source),
            max_workers=1,
        )
        stub.assert_no_pending_responses()
    assert isinstance(results[0].error, ClientError)
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].error_code == "AccessDenied"
    assert results[0].error.__traceback__ is None
    assert results[1].value == "111111111111"


@pytest.mark.parametrize("actual_account", ["111111111111", "222222222222"])
def test_real_named_profile_loading_and_identity_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sdk_source: Any,
    actual_account: str,
) -> None:
    (tmp_path / "config").write_text("[profile audit]\nregion = eu-west-1\n")
    (tmp_path / "credentials").write_text(
        "[audit]\naws_access_key_id = PROFILETEST000000000\naws_secret_access_key = synthetic-secret\n"
    )
    _, clients = sdk_source
    original_client = boto3.session.Session.client

    def client(self: Any, service_name: str, **kwargs: Any) -> Any:
        if service_name == "sts":
            return clients["sts"]
        return original_client(self, service_name, **kwargs)

    monkeypatch.setattr(boto3.session.Session, "client", client)
    called = []

    def worker(session: Any, _account: Any) -> str:
        called.append(session)
        return session.get_credentials().get_frozen_credentials().access_key

    with Stubber(clients["sts"]) as stub:
        stub.add_response(
            "get_caller_identity",
            {
                "Account": actual_account,
                "UserId": "AIDATEST",
                "Arn": f"arn:aws:iam::{actual_account}:user/test",
            },
            {},
        )
        result = map_accounts(
            worker,
            accounts=["111111111111"],
            auth=Profile("audit", verify_account_id=True),
        )[0]
        stub.assert_no_pending_responses()
    assert result.profile_name == "audit"
    if actual_account == "111111111111":
        assert result.value == "PROFILETEST000000000"
    else:
        assert result.phase is ExecutionPhase.AUTH
        assert isinstance(result.error, ValueError)
        assert called == []


@pytest.mark.parametrize("outcome", ["success", "denied", "expired"])
def test_real_identity_center_provider_resolves_before_callback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sdk_source: Any, outcome: str
) -> None:
    (tmp_path / "config").write_text(
        "[profile audit]\nregion = eu-west-1\nsso_session = work\n"
        "sso_account_id = 111111111111\nsso_role_name = ReadOnly\n"
        "[sso-session work]\nsso_start_url = https://example.awsapps.com/start\n"
        "sso_region = eu-west-1\n"
    )
    session = boto3.Session(profile_name="audit")
    _, clients = sdk_source
    expiry = datetime.now(timezone.utc) + timedelta(
        hours=-1 if outcome == "expired" else 1
    )
    token_cache = {
        sha1(b"work", usedforsecurity=False).hexdigest(): {
            "accessToken": "synthetic-access-token",
            "expiresAt": expiry.isoformat(),
        }
    }
    # Use actual Botocore token and credential providers, injecting only their
    # cache and transport. No contributor token files or SSO login are accessed.
    token_provider = SSOTokenProvider(
        session._session, cache=token_cache, profile_name="audit"
    )
    provider = SSOProvider(
        load_config=lambda: session._session.full_config,
        client_creator=lambda *_args, **_kwargs: clients["sso"],
        profile_name="audit",
        cache={},
        token_cache={},
        token_provider=token_provider,
    )
    session._session.register_component(
        "credential_provider", CredentialResolver([provider])
    )
    monkeypatch.setattr("runacross.auth.boto3.Session", lambda **_kwargs: session)
    called = []

    def worker(callback_session: Any, _account: Any) -> str:
        called.append(callback_session)
        return callback_session.get_credentials().get_frozen_credentials().access_key

    params = {
        "accountId": "111111111111",
        "roleName": "ReadOnly",
        "accessToken": "synthetic-access-token",
    }
    with Stubber(clients["sso"]) as stub:
        if outcome == "success":
            stub.add_response(
                "get_role_credentials",
                {
                    "roleCredentials": {
                        "accessKeyId": "SSOTEST0000000000000",
                        "secretAccessKey": "s" * 40,
                        "sessionToken": "synthetic-session-token",
                        "expiration": int(expiry.timestamp() * 1000),
                    }
                },
                params,
            )
        elif outcome == "denied":
            stub.add_client_error(
                "get_role_credentials",
                "UnauthorizedException",
                "synthetic denial",
                expected_params=params,
            )
        result = map_accounts(worker, accounts=["111111111111"], auth=Profile("audit"))[
            0
        ]
        stub.assert_no_pending_responses()
    if outcome == "success":
        assert result.value == "SSOTEST0000000000000"
        assert len(called) == 1
    else:
        assert result.phase is ExecutionPhase.AUTH
        assert result.error is not None
        assert called == []
