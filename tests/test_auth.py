from __future__ import annotations

from typing import Any, cast

import pytest
from boto3.session import Session

from runacross import (
    Account,
    ExecutionPhase,
    Profile,
    Role,
    map_account_regions,
    map_accounts,
)
from runacross.auth import resolve_auth


class RecordingSession:
    def __init__(
        self,
        profile_name: str | None = None,
        region_name: str | None = None,
        **_kwargs: Any,
    ) -> None:
        self.profile_name = profile_name
        self.region_name = region_name or "eu-west-1"
        self.credentials = RecordingCredentials()

    def get_credentials(self) -> RecordingCredentials | None:
        return self.credentials


class RecordingCredentials:
    def __init__(self) -> None:
        self.freeze_calls = 0

    def get_frozen_credentials(self) -> object:
        self.freeze_calls += 1
        return object()


class IdentitySession(RecordingSession):
    def __init__(
        self,
        profile_name: str | None = None,
        region_name: str | None = None,
        *,
        account_id: str = "111111111111",
        **kwargs: Any,
    ) -> None:
        super().__init__(profile_name, region_name, **kwargs)
        self.account_id = account_id
        self.sts_calls = 0
        self.identity_response: object = {
            "Account": account_id,
            "Arn": f"arn:aws:iam::{account_id}:user/test",
            "UserId": "AIDATEST",
        }

    def client(self, service_name: str, **_kwargs: Any) -> Any:
        del service_name
        parent = self

        class STS:
            def get_caller_identity(self) -> object:
                parent.sts_calls += 1
                return parent.identity_response

        return STS()


def test_profile_requires_exactly_one_strategy() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Profile()
    with pytest.raises(ValueError, match="exactly one"):
        Profile(
            pattern="{account_id}-audit",
            mapping={"111111111111": "audit"},
        )


def test_profile_pattern_rejects_unknown_placeholders() -> None:
    with pytest.raises(ValueError, match="account_id or name"):
        Profile("{account_id}-{role}")


def test_profile_pattern_resolves_account_id() -> None:
    profile = Profile("{account_id}-script-SecurityAudit")

    assert (
        profile.profile_name(Account(id="111111111111"))
        == "111111111111-script-SecurityAudit"
    )


def test_profile_pattern_requires_account_name_when_used() -> None:
    profile = Profile("{account_id}-{name}")

    with pytest.raises(ValueError, match="has no name"):
        profile.profile_name(Account(id="111111111111"))
    assert (
        profile.profile_name(Account(id="111111111111", name="prod"))
        == "111111111111-prod"
    )


def test_profile_mapping_resolves_and_rejects_unknown_accounts() -> None:
    profile = Profile(mapping={"111111111111": "prod-security"})

    assert profile.profile_name(Account(id="111111111111")) == "prod-security"
    with pytest.raises(KeyError, match="222222222222"):
        profile.profile_name(Account(id="222222222222"))


def test_profile_mapping_rejects_invalid_account_ids() -> None:
    with pytest.raises(ValueError, match="12 ASCII digits"):
        Profile(mapping={"123": "prod-security"})


def test_profile_resolver_is_used() -> None:
    profile = Profile(resolver=lambda account: f"sso-{account.id}")

    assert profile.profile_name(Account(id="111111111111")) == "sso-111111111111"


def test_profile_rejects_invalid_construction_types() -> None:
    with pytest.raises(TypeError, match="non-empty string"):
        Profile(pattern=123)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="resolver must be callable"):
        Profile(resolver="not-callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mapping must be a mapping"):
        Profile(mapping=[("111111111111", "audit")])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mapping keys"):
        Profile(mapping={111111111111: "audit"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="non-empty string"):
        Profile(mapping={"111111111111": ""})


def test_profile_resolver_must_return_a_name() -> None:
    profile = Profile(resolver=lambda _account: "")

    with pytest.raises(ValueError, match="non-empty string"):
        profile.profile_name(Account(id="111111111111"))


def test_bound_profile_has_no_reporting_region() -> None:
    bound = Profile("{account_id}-audit").bind(max_workers=1, botocore_config=None)

    assert bound.reporting_region() is None


def test_resolve_auth_rejects_objects_without_bind() -> None:
    with pytest.raises(TypeError, match="Role or Profile"):
        resolve_auth(
            auth=object(),  # type: ignore[arg-type]
            role_name=None,
            role_session_name="runacross",
            external_id=None,
            duration_seconds=None,
            source_session=None,
        )


def test_map_accounts_uses_profile_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[RecordingSession] = []

    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> RecordingSession:
        session = RecordingSession(profile_name, region_name, **kwargs)
        created.append(session)
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda session, _account: cast(RecordingSession, session).profile_name,
        accounts=["111111111111", "222222222222"],
        auth=Profile("{account_id}-script-SecurityAudit"),
    )

    assert [result.value for result in results] == [
        "111111111111-script-SecurityAudit",
        "222222222222-script-SecurityAudit",
    ]
    assert [result.profile_name for result in results] == [
        "111111111111-script-SecurityAudit",
        "222222222222-script-SecurityAudit",
    ]
    assert [result.role_name for result in results] == [None, None]
    assert [session.profile_name for session in created] == [
        "111111111111-script-SecurityAudit",
        "222222222222-script-SecurityAudit",
    ]
    assert [session.credentials.freeze_calls for session in created] == [1, 1]


def test_profile_without_credentials_is_an_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **_kwargs: Any,
    ) -> RecordingSession:
        session = RecordingSession(profile_name, region_name)
        session.credentials = None  # type: ignore[assignment]
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit"),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].error is not None
    assert "did not provide credentials" in str(results[0].error)


def test_profile_credential_resolution_error_is_an_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExpiredCredentials(RecordingCredentials):
        def get_frozen_credentials(self) -> object:
            raise RuntimeError("Token has expired")

    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **_kwargs: Any,
    ) -> RecordingSession:
        session = RecordingSession(profile_name, region_name)
        session.credentials = ExpiredCredentials()
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit"),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].error is not None
    assert "Token has expired" in str(results[0].error)


def test_profile_without_region_is_an_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **_kwargs: Any,
    ) -> RecordingSession:
        session = RecordingSession(profile_name, region_name)
        session.region_name = region_name
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit"),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].error is not None
    assert "must have a region" in str(results[0].error)


def test_resolve_auth_builds_role_from_role_name() -> None:
    source = cast(Session, type("S", (), {"region_name": "eu-west-1"})())
    auth = resolve_auth(
        auth=None,
        role_name="SecurityAuditRole",
        role_session_name="runacross",
        external_id=None,
        duration_seconds=900,
        source_session=source,
    )

    assert isinstance(auth, Role)
    assert auth.name == "SecurityAuditRole"
    assert auth.duration_seconds == 900


def test_role_reporting_region_matches_source_session() -> None:
    class FakeSource:
        region_name = "eu-west-1"

        def client(self, service_name: str, *, config: object) -> object:
            del service_name, config
            return type("STS", (), {"meta": type("M", (), {"partition": "aws"})()})()

    bound = Role(
        "SecurityAuditRole",
        source_session=cast(Session, FakeSource()),
    ).bind(max_workers=1, botocore_config=None)

    assert bound.reporting_region() == "eu-west-1"


def test_profile_rejects_non_bool_verify_account_id() -> None:
    with pytest.raises(TypeError, match="verify_account_id must be a bool"):
        Profile("{account_id}-audit", verify_account_id=1)  # type: ignore[arg-type]


def test_verify_account_id_accepts_matching_caller_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[IdentitySession] = []

    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> IdentitySession:
        session = IdentitySession(
            profile_name,
            region_name,
            account_id="111111111111",
            **kwargs,
        )
        created.append(session)
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit", verify_account_id=True),
    )

    assert results[0].success is True
    assert results[0].profile_name == "111111111111-audit"
    assert created[0].sts_calls == 1


def test_verify_account_id_rejects_mismatched_caller_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> IdentitySession:
        return IdentitySession(
            profile_name,
            region_name,
            account_id="999999999999",
            **kwargs,
        )

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit", verify_account_id=True),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].profile_name == "111111111111-audit"
    assert results[0].error is not None
    assert "authenticated as account 999999999999" in str(results[0].error)
    assert "expected 111111111111" in str(results[0].error)


def test_verify_account_id_is_skipped_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[IdentitySession] = []

    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> IdentitySession:
        session = IdentitySession(profile_name, region_name, **kwargs)
        created.append(session)
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit"),
    )

    assert results[0].success is True
    assert created[0].sts_calls == 0


def test_missing_profile_mapping_keeps_auth_failure_without_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("runacross.auth.boto3.Session", RecordingSession)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile(mapping={"222222222222": "other-audit"}),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].profile_name is None


def test_verify_account_id_rejects_a_missing_account_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> IdentitySession:
        session = IdentitySession(profile_name, region_name, **kwargs)
        session.identity_response = {"Arn": "arn:aws:iam::111111111111:user/test"}
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit", verify_account_id=True),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH
    assert results[0].error is not None
    assert "did not return an Account" in str(results[0].error)


def test_verify_account_id_rejects_a_non_mapping_identity_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_session(
        profile_name: str | None = None,
        region_name: str | None = None,
        **kwargs: Any,
    ) -> IdentitySession:
        session = IdentitySession(profile_name, region_name, **kwargs)
        session.identity_response = "not-a-mapping"
        return session

    monkeypatch.setattr("runacross.auth.boto3.Session", fake_session)

    results = map_accounts(
        lambda _session, account: account.id,
        accounts=["111111111111"],
        auth=Profile("{account_id}-audit", verify_account_id=True),
    )

    assert results[0].success is False
    assert results[0].phase is ExecutionPhase.AUTH


@pytest.mark.parametrize("regional", [False, True])
def test_profile_resolver_runs_once_per_target_and_reports_actual_profile(
    monkeypatch: pytest.MonkeyPatch, regional: bool
) -> None:
    monkeypatch.setattr("runacross.auth.boto3.Session", RecordingSession)
    calls: list[str] = []

    def resolve(account: Account) -> str:
        calls.append(account.id)
        return f"profile-{len(calls)}"

    auth = Profile(resolver=resolve)
    if regional:
        results = map_account_regions(
            lambda session, _account, _region: session.profile_name,
            accounts=["111111111111"],
            regions=["eu-west-1", "us-east-1"],
            auth=auth,
            max_workers=1,
        )
    else:
        results = map_accounts(
            lambda session, _account: session.profile_name,
            accounts=["111111111111", "222222222222"],
            auth=auth,
            max_workers=1,
        )
    assert len(calls) == 2
    assert [r.value for r in results] == ["profile-1", "profile-2"]
    assert [r.profile_name for r in results] == [r.value for r in results]


@pytest.mark.parametrize("regional", [False, True])
def test_resolver_failure_is_isolated_and_does_not_reuse_previous_identity(
    monkeypatch: pytest.MonkeyPatch, regional: bool
) -> None:
    monkeypatch.setattr("runacross.auth.boto3.Session", RecordingSession)

    def resolve(account: Account) -> str:
        if account.id == "222222222222":
            raise RuntimeError("resolver failed")
        return "audit"

    kwargs = {
        "accounts": ["111111111111", "222222222222", "333333333333"],
        "auth": Profile(resolver=resolve),
        "max_workers": 1,
    }
    if regional:
        results = map_account_regions(
            lambda _session, account, _region: account.id,
            regions=["eu-west-1"],
            **kwargs,
        )
    else:
        results = map_accounts(lambda _session, account: account.id, **kwargs)
    assert results.success_count == 2
    assert results[1].phase is ExecutionPhase.AUTH
    assert isinstance(results[1].error, RuntimeError)
    assert [r.profile_name for r in results] == ["audit", None, "audit"]
