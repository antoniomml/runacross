from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from botocore.config import Config

from runacross import Account, ConfigError
from runacross.profiles import list_accounts


class FakeBotocoreSession:
    config: ClassVar[dict[str, Any]] = {}

    @property
    def full_config(self) -> dict[str, Any]:
        return self.config


def shared_config(
    profiles: dict[str, dict[str, str]],
    *,
    sessions: tuple[str, ...] = ("control-tower", "legacy"),
) -> dict[str, Any]:
    return {
        "profiles": profiles,
        "sso_sessions": {name: {"sso_region": "eu-west-1"} for name in sessions},
    }


def install_config(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
) -> None:
    FakeBotocoreSession.config = config
    monkeypatch.setattr("runacross.profiles.BotocoreSession", FakeBotocoreSession)


def test_list_accounts_filters_by_pattern_and_sso_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(
        monkeypatch,
        shared_config(
            {
                "AWS-Infosec-111111111111": {
                    "sso_session": "control-tower",
                    "sso_account_id": "111111111111",
                },
                "AWS-Infosec-222222222222": {
                    "sso_session": "legacy",
                    "sso_account_id": "222222222222",
                },
                "AWS-Infosec-333333333333": {
                    "sso_session": "control-tower",
                    "sso_account_id": "333333333333",
                },
                "AWS-Developer-444444444444": {
                    "sso_session": "control-tower",
                    "sso_account_id": "444444444444",
                },
            }
        ),
    )

    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
    )

    assert accounts == [
        Account(id="111111111111"),
        Account(id="333333333333"),
    ]


def test_list_accounts_excludes_requested_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(
        monkeypatch,
        shared_config(
            {
                "AWS-Infosec-111111111111": {
                    "sso_session": "control-tower",
                    "sso_account_id": "111111111111",
                },
                "AWS-Infosec-222222222222": {
                    "sso_session": "control-tower",
                    "sso_account_id": "222222222222",
                },
            }
        ),
    )

    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
        exclude_accounts=["111111111111"],
    )

    assert accounts == [Account(id="222222222222")]


def test_list_accounts_limit_keeps_first_matching_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(
        monkeypatch,
        shared_config(
            {
                "AWS-Infosec-111111111111": {
                    "sso_session": "control-tower",
                    "sso_account_id": "111111111111",
                },
                "AWS-Infosec-222222222222": {
                    "sso_session": "control-tower",
                    "sso_account_id": "222222222222",
                },
                "AWS-Infosec-333333333333": {
                    "sso_session": "control-tower",
                    "sso_account_id": "333333333333",
                },
            }
        ),
    )

    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
        limit=2,
    )

    assert accounts == [
        Account(id="111111111111"),
        Account(id="222222222222"),
    ]


def test_list_accounts_honors_aws_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "aws-config"
    config_file.write_text(
        """
[profile AWS-Infosec-111111111111]
sso_session = control-tower
sso_account_id = 111111111111
sso_role_name = Infosec
region = eu-west-1

[profile AWS-Infosec-222222222222]
sso_session = legacy
sso_account_id = 222222222222
sso_role_name = Infosec
region = eu-west-1

[sso-session control-tower]
sso_start_url = https://control.example.awsapps.com/start
sso_region = eu-west-1

[sso-session legacy]
sso_start_url = https://legacy.example.awsapps.com/start
sso_region = eu-west-1
""".strip()
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing"))

    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
    )

    assert accounts == [Account(id="111111111111")]


def test_list_accounts_rejects_unknown_sso_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(monkeypatch, shared_config({}))

    with pytest.raises(ConfigError, match="was not found"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="missing",
        )


def test_list_accounts_rejects_account_id_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(
        monkeypatch,
        shared_config(
            {
                "AWS-Infosec-111111111111": {
                    "sso_session": "control-tower",
                    "sso_account_id": "222222222222",
                }
            }
        ),
    )

    with pytest.raises(ConfigError, match="identifies account 111111111111"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
        )


def test_list_accounts_requires_sso_account_id_on_a_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(
        monkeypatch,
        shared_config(
            {
                "AWS-Infosec-111111111111": {
                    "sso_session": "control-tower",
                }
            }
        ),
    )

    with pytest.raises(ConfigError, match="must define a string sso_account_id"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
        )


@pytest.mark.parametrize(
    "pattern",
    [
        "AWS-Infosec",
        "AWS-{name}-{account_id}",
        "AWS-{account_id}-{account_id}",
        "AWS-{account_id!r}",
    ],
)
def test_list_accounts_rejects_unsafe_patterns(
    pattern: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(monkeypatch, shared_config({}))

    with pytest.raises(ConfigError, match="pattern"):
        list_accounts(pattern=pattern, sso_session="control-tower")


def test_list_accounts_requires_both_organization_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(monkeypatch, shared_config({}))

    with pytest.raises(ConfigError, match="organization_id"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
            organization_id="invalid",
        )
    with pytest.raises(TypeError, match="provided together"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
            organization_profile="AWSAdministratorAccess-111111111111",
        )


class FakeCredentials:
    def __init__(self) -> None:
        self.freeze_calls = 0

    def get_frozen_credentials(self) -> object:
        self.freeze_calls += 1
        return object()


class FakeOrganizationsClient:
    def __init__(self, organization_id: str) -> None:
        self.organization_id = organization_id
        self.describe_calls = 0

    def describe_organization(self) -> dict[str, Any]:
        self.describe_calls += 1
        return {"Organization": {"Id": self.organization_id}}


class FakeBotoSession:
    def __init__(self, profile_name: str, client: FakeOrganizationsClient) -> None:
        self.profile_name = profile_name
        self.region_name = "eu-west-1"
        self.credentials = FakeCredentials()
        self.organizations_client = client
        self.client_calls: list[tuple[str, Config]] = []

    def get_credentials(self) -> FakeCredentials:
        return self.credentials

    def client(
        self,
        service_name: str,
        *,
        config: Config,
    ) -> FakeOrganizationsClient:
        self.client_calls.append((service_name, config))
        return self.organizations_client


def organization_config() -> dict[str, Any]:
    return shared_config(
        {
            "AWS-Infosec-111111111111": {
                "sso_session": "control-tower",
                "sso_account_id": "111111111111",
            },
            "AWSAdministratorAccess-999999999999": {
                "sso_session": "control-tower",
                "sso_account_id": "999999999999",
            },
        }
    )


def test_list_accounts_validates_organization_without_listing_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(monkeypatch, organization_config())
    client = FakeOrganizationsClient("o-exampleorgid")
    created: list[FakeBotoSession] = []

    def fake_session(profile_name: str) -> FakeBotoSession:
        session = FakeBotoSession(profile_name, client)
        created.append(session)
        return session

    monkeypatch.setattr("runacross.profiles.boto3.Session", fake_session)

    accounts = list_accounts(
        pattern="AWS-Infosec-{account_id}",
        sso_session="control-tower",
        organization_id="o-exampleorgid",
        organization_profile="AWSAdministratorAccess-999999999999",
    )

    assert accounts == [Account(id="111111111111")]
    assert client.describe_calls == 1
    assert created[0].profile_name == "AWSAdministratorAccess-999999999999"
    assert created[0].credentials.freeze_calls == 1
    assert created[0].client_calls[0][0] == "organizations"
    assert created[0].client_calls[0][1].retries == {
        "mode": "standard",
        "total_max_attempts": 3,
    }


def test_list_accounts_rejects_organization_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_config(monkeypatch, organization_config())
    client = FakeOrganizationsClient("o-otherorgid1")
    monkeypatch.setattr(
        "runacross.profiles.boto3.Session",
        lambda profile_name: FakeBotoSession(profile_name, client),
    )

    with pytest.raises(ConfigError, match="does not match"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
            organization_id="o-exampleorgid",
            organization_profile="AWSAdministratorAccess-999999999999",
        )


def test_organization_profile_must_use_selected_sso_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = organization_config()
    config["profiles"]["AWSAdministratorAccess-999999999999"]["sso_session"] = "legacy"
    install_config(monkeypatch, config)

    with pytest.raises(ConfigError, match="not 'control-tower'"):
        list_accounts(
            pattern="AWS-Infosec-{account_id}",
            sso_session="control-tower",
            organization_id="o-exampleorgid",
            organization_profile="AWSAdministratorAccess-999999999999",
        )
