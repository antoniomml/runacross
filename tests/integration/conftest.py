from __future__ import annotations

from typing import Any

import boto3
import pytest


@pytest.fixture
def sdk_source(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, Any]]:
    """Real SDK clients; only route Session.client to the stubbed instances."""
    session = boto3.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name="eu-west-1",
    )
    clients = {
        service: session.client(service)
        for service in ("sts", "organizations", "account", "sso")
    }

    def client(service_name: str, **_kwargs: Any) -> Any:
        return clients[service_name]

    monkeypatch.setattr(session, "client", client)
    return session, clients
