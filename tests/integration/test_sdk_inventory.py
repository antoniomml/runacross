from __future__ import annotations

import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from runacross import ExecutionPhase, Role, map_account_regions
from runacross.organizations import list_accounts


def test_organization_to_multiregion_inventory_with_partial_failures(
    sdk_source: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, clients = sdk_source
    example = runpy.run_path(
        str(Path(__file__).parents[2] / "examples" / "ec2_inventory.py")
    )
    inventory = example["list_instance_ids"]
    original_client = boto3.session.Session.client

    def client(self: Any, service_name: str, **kwargs: Any) -> Any:
        if service_name == "account":
            return clients["account"]
        return original_client(self, service_name, **kwargs)

    monkeypatch.setattr(boto3.session.Session, "client", client)
    observed = []

    def observe(result: Any, *, completed: int, total: int) -> None:
        observed.append((result.account.id, completed, total))

    def worker(session: Any, account: Any, region: str) -> list[str]:
        ec2 = session.client("ec2")
        monkeypatch.setattr(session, "client", lambda *_args, **_kwargs: ec2)
        with Stubber(ec2) as stub:
            if region == "us-east-1":
                stub.add_client_error(
                    "describe_instances",
                    "UnauthorizedOperation",
                    "synthetic denial",
                    expected_params={},
                )
            else:
                stub.add_response(
                    "describe_instances",
                    {"Reservations": [], "NextToken": "next-page"},
                    {},
                )
                stub.add_response(
                    "describe_instances",
                    {
                        "Reservations": [
                            {
                                "Instances": [
                                    {"InstanceId": "i-00000000000000001"},
                                    {"InstanceId": "i-00000000000000002"},
                                ]
                            }
                        ]
                    },
                    {"NextToken": "next-page"},
                )
            try:
                return inventory(session, account, region)
            finally:
                stub.assert_no_pending_responses()

    with (
        Stubber(clients["organizations"]) as org,
        Stubber(clients["sts"]) as sts,
        Stubber(clients["account"]) as regions,
    ):
        org.add_response(
            "list_accounts",
            {
                "Accounts": [
                    {"Id": "111111111111", "State": "ACTIVE"},
                    {"Id": "222222222222", "State": "ACTIVE"},
                ]
            },
            {},
        )
        sts.add_response(
            "assume_role",
            {
                "Credentials": {
                    "AccessKeyId": "ASIATEST000000000000",
                    "SecretAccessKey": "s" * 40,
                    "SessionToken": "synthetic-token",
                    "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
                }
            },
            {
                "RoleArn": "arn:aws:iam::111111111111:role/audit",
                "RoleSessionName": "runacross",
            },
        )
        sts.add_client_error(
            "assume_role",
            "AccessDenied",
            "synthetic denial",
            expected_params={
                "RoleArn": "arn:aws:iam::222222222222:role/audit",
                "RoleSessionName": "runacross",
            },
        )
        regions.add_response(
            "list_regions",
            {
                "Regions": [
                    {
                        "RegionName": "eu-west-1",
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                    },
                    {
                        "RegionName": "us-east-1",
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                    },
                ]
            },
            {"RegionOptStatusContains": ["ENABLED", "ENABLED_BY_DEFAULT"]},
        )
        accounts = list_accounts(session=source)
        results = map_account_regions(
            worker,
            accounts=accounts,
            auth=Role("audit", source_session=source),
            discover_regions=True,
            max_workers=1,
            on_result=observe,
        )
        for stub in (org, sts, regions):
            stub.assert_no_pending_responses()
    assert results[0].value == ["i-00000000000000001", "i-00000000000000002"]
    assert results[1].phase is ExecutionPhase.WORKER
    assert results[1].error_code == "UnauthorizedOperation"
    assert results[2].phase is ExecutionPhase.AUTH
    assert results[2].error_code == "AccessDenied"
    assert results.summary() == {
        "total": 3,
        "success_count": 1,
        "failure_count": 2,
        "failures_by_phase": {"auth": 1, "worker": 1},
    }
    assert observed == [
        ("222222222222", 1, 3),
        ("111111111111", 2, 3),
        ("111111111111", 3, 3),
    ]
