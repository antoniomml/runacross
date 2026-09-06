from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from botocore.httpsession import URLLib3Session


@pytest.fixture(autouse=True)
def isolated_aws_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests never use the contributor's credentials or send SDK HTTP requests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))

    def blocked_send(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("live AWS requests are forbidden in unit tests")

    monkeypatch.setattr(URLLib3Session, "send", blocked_send)
