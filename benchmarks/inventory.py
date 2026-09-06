"""Offline paginated EC2 inventory with real SDK clients and synthetic latency.

Run from an editable install: python benchmarks/inventory.py
All credentials/responses are synthetic; SDK HTTP transport is blocked.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import time
import tracemalloc
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import boto3
from botocore.stub import ANY, Stubber

from runacross import Account, Role, map_account_regions

REGIONS = ["eu-west-1", "us-east-1", "ap-southeast-2"]


def measure(args: argparse.Namespace, workers: int) -> dict[str, Any]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    source = boto3.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name="eu-west-1",
    )
    sts = source.client("sts")
    regions = REGIONS[: args.regions]
    account_ids = [f"{index + 1:012d}" for index in range(args.accounts)]

    def worker(session: Any, account: Account, region: str) -> list[str]:
        ec2 = session.client("ec2")
        ordinal = (int(account.id) - 1) * len(regions) + regions.index(region) + 1
        fails = args.failure_every > 0 and ordinal % args.failure_every == 0
        ec2.meta.events.register(
            "before-parameter-build.ec2.DescribeInstances",
            lambda **_kwargs: time.sleep(args.latency_ms / 1000),
        )
        with closing(ec2), Stubber(ec2) as stub:
            for page in range(args.pages):
                params = {} if page == 0 else {"NextToken": f"page-{page}"}
                if fails and page == args.pages - 1:
                    stub.add_client_error(
                        "describe_instances",
                        "UnauthorizedOperation",
                        "synthetic denial",
                        expected_params=params,
                    )
                else:
                    response: dict[str, Any] = {
                        "Reservations": [
                            {
                                "Instances": [
                                    {"InstanceId": f"i-{page * args.items + item:017x}"}
                                    for item in range(args.items)
                                ]
                            }
                        ]
                    }
                    if page < args.pages - 1:
                        response["NextToken"] = f"page-{page + 1}"
                    stub.add_response("describe_instances", response, params)
            try:
                return [
                    instance["InstanceId"]
                    for page in ec2.get_paginator("describe_instances").paginate()
                    for reservation in page["Reservations"]
                    for instance in reservation["Instances"]
                ]
            finally:
                stub.assert_no_pending_responses()

    with (
        closing(sts),
        Stubber(sts) as stub,
        patch.object(source, "client", return_value=sts),
    ):
        for _ in account_ids:
            stub.add_response(
                "assume_role",
                {
                    "Credentials": {
                        "AccessKeyId": "ASIATEST000000000000",
                        "SecretAccessKey": "s" * 40,
                        "SessionToken": "synthetic-token",
                        "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
                    }
                },
                {"RoleArn": ANY, "RoleSessionName": "runacross"},
            )
        results = map_account_regions(
            worker,
            accounts=account_ids,
            regions=regions,
            auth=Role("audit", source_session=source),
            max_workers=workers,
        )
        stub.assert_no_pending_responses()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total = args.accounts * len(regions)
    expected_failures = total // args.failure_every if args.failure_every else 0
    assert len(results) == total
    assert [(r.account.id, r.region) for r in results] == [
        (account, region) for account in account_ids for region in regions
    ]
    assert results.failure_count == expected_failures
    assert all(
        result.error_code == "UnauthorizedOperation" for result in results.failed
    )
    returned_items = sum(len(result.unwrap()) for result in results.successful)
    assert returned_items == (total - expected_failures) * args.pages * args.items
    return {
        "workers": workers,
        "seconds": elapsed,
        "peak_mib": peak / 1024**2,
        **results.summary(),
        "returned_instances": returned_items,
        "assume_role_calls": args.accounts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=int, default=10)
    parser.add_argument("--regions", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--items", type=int, default=20)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 10])
    parser.add_argument("--latency-ms", type=float, default=5)
    parser.add_argument("--failure-every", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.accounts, args.pages, args.items, args.repeats, *args.workers) < 1:
        parser.error("counts must be positive")
    if args.latency_ms < 0 or args.failure_every < 0:
        parser.error("latency and failure interval cannot be negative")
    runs = []
    with (
        patch.dict(
            os.environ,
            {
                "AWS_CONFIG_FILE": os.devnull,
                "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                "AWS_EC2_METADATA_DISABLED": "true",
            },
        ),
        patch(
            "botocore.httpsession.URLLib3Session.send",
            side_effect=AssertionError("live HTTP forbidden"),
        ),
    ):
        os.environ.pop("AWS_PROFILE", None)
        os.environ.pop("AWS_DEFAULT_PROFILE", None)
        for workers in args.workers:
            samples = [measure(args, workers) for _ in range(args.repeats)]
            run = samples[-1]
            for key in ("seconds", "peak_mib"):
                run[key] = round(
                    statistics.median(sample[key] for sample in samples), 4
                )
            runs.append(run)
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "boto3": boto3.__version__,
                "settings": vars(args),
                "runs": runs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
