"""Read-only live validation of Role authentication for the 1.0 candidate.

Run this script manually from an editable or installed environment against
disposable or read-only AWS accounts:

    python validation/role_consumer.py \
        --account 111111111111 \
        --account 222222222222 \
        --role-name SecurityAuditRole \
        --source-profile security \
        --region eu-west-1 \
        --regions eu-west-1,us-east-1 \
        --report role-report.json

The script performs only read-only calls: ``sts:GetCallerIdentity`` and, when
``--regions`` or ``--discover-regions`` is used, ``account:ListRegions``. It
exits non-zero when a target fails, when an identity does not match its target
account, or when an expected authentication failure is missing.
"""

from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import botocore
from boto3.session import Session

from runacross import (
    Account,
    ExecutionPhase,
    RegionResults,
    Role,
    RunResults,
    __version__,
    map_account_regions,
    map_accounts,
)
from runacross.models import AccountRegionResult, AccountResult

Identity = dict[str, str]
Outcome = AccountRegionResult[Identity] | AccountResult[Identity]
OutcomeList = RunResults[Identity] | RegionResults[Identity]


def caller_identity(session: Session, account: Account) -> Identity:
    """Return the STS identity for one target account."""

    response: dict[str, Any] = session.client("sts").get_caller_identity()
    return {
        "account": str(response["Account"]),
        "arn": str(response["Arn"]),
        "user_id": str(response["UserId"]),
    }


def caller_identity_by_region(
    session: Session,
    account: Account,
    region: str,
) -> Identity:
    """Return the STS identity for one account and Region pair."""

    identity = caller_identity(session, account)
    identity["region"] = region
    return identity


def outcomes(results: OutcomeList) -> list[tuple[str, str | None, Outcome]]:
    """Normalize account and account-by-Region results for verification."""

    return [
        (result.account.id, getattr(result, "region", None), result)
        for result in results
    ]


def verify_outcomes(
    pairs: Sequence[tuple[str, str | None, Outcome]],
    *,
    expected_failures: frozenset[str],
    expected_role: str,
) -> list[str]:
    """Return every contract problem found in the observed outcomes."""

    problems: list[str] = []
    for account_id, region, result in pairs:
        label = account_id if region is None else f"{account_id}/{region}"
        if account_id in expected_failures:
            if result.success or result.phase is not ExecutionPhase.AUTH:
                problems.append(
                    f"{label}: expected an auth failure, got "
                    f"success={result.success} phase={result.phase}"
                )
            continue
        if not result.success:
            problems.append(f"{label}: {result.phase} failure: {result.error!r}")
            continue
        if result.value is None:
            problems.append(f"{label}: successful result without an identity value")
            continue
        if result.value["account"] != account_id:
            problems.append(
                f"{label}: sts:GetCallerIdentity returned account "
                f"{result.value['account']}"
            )
        if region is not None and result.value.get("region") != region:
            problems.append(f"{label}: identity Region {result.value.get('region')!r}")
        if result.role_name != expected_role:
            problems.append(f"{label}: role metadata {result.role_name!r}")
    return problems


def environment() -> dict[str, str]:
    """Return the versions that must accompany every evidence report."""

    return {
        "runacross": __version__,
        "python": platform.python_version(),
        "boto3": str(boto3.__version__),
        "botocore": str(botocore.__version__),
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--account",
        action="append",
        default=[],
        required=True,
        metavar="ID",
        help="target account ID (repeatable)",
    )
    command.add_argument(
        "--role-name",
        required=True,
        help="IAM role name or path assumed in every target",
    )
    command.add_argument(
        "--role-session-name",
        default="runacross-validation",
        help="AssumeRole session name",
    )
    command.add_argument(
        "--source-profile",
        default=None,
        help="source AWS profile used to call STS",
    )
    command.add_argument("--external-id", default=None, help="AssumeRole external ID")
    command.add_argument(
        "--duration-seconds",
        type=int,
        default=None,
        help="AssumeRole duration (900-43200)",
    )
    command.add_argument(
        "--region",
        default="eu-west-1",
        help="source Region used to create the STS client",
    )
    command.add_argument(
        "--regions",
        default=None,
        help="comma-separated Regions for account-by-Region execution",
    )
    command.add_argument(
        "--discover-regions",
        action="store_true",
        help="also run enabled-Region discovery through account:ListRegions",
    )
    command.add_argument(
        "--expect-failure",
        action="append",
        default=[],
        metavar="ID",
        help="account expected to fail in phase auth (repeatable)",
    )
    command.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="concurrent targets",
    )
    command.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write a JSON evidence report to this path",
    )
    return command


def main(argv: Sequence[str] | None = None) -> int:
    command = parser()
    args = command.parse_args(argv)
    try:
        accounts = [Account(id=value) for value in args.account]
    except (TypeError, ValueError) as error:
        command.error(f"invalid --account: {error}")
    expected_failures = frozenset(str(value) for value in args.expect_failure)
    try:
        source = boto3.Session(
            profile_name=args.source_profile,
            region_name=str(args.region),
        )
        auth = Role(
            name=args.role_name,
            session_name=args.role_session_name,
            external_id=args.external_id,
            duration_seconds=args.duration_seconds,
            source_session=source,
        )
    except Exception as error:
        command.error(f"cannot configure Role authentication: {error}")
    report: dict[str, Any] = {
        "environment": environment(),
        "auth": "Role",
        "role_name": args.role_name,
        "source_profile": args.source_profile,
        "accounts": [account.id for account in accounts],
        "expected_failures": sorted(expected_failures),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    problems: list[str] = []

    account_results = map_accounts(
        caller_identity,
        accounts=accounts,
        auth=auth,
        max_workers=args.max_workers,
    )
    problems.extend(
        verify_outcomes(
            outcomes(account_results),
            expected_failures=expected_failures,
            expected_role=auth.name,
        )
    )
    if [result.account.id for result in account_results] != [
        account.id for account in accounts
    ]:
        problems.append("account results lost input order or membership")
    report["account_summary"] = account_results.summary()
    report["account_results"] = account_results.to_dicts()
    print(
        f"accounts: {account_results.success_count} ok, "
        f"{account_results.failure_count} failed"
    )

    if args.regions:
        regions = [
            part.strip() for part in str(args.regions).split(",") if part.strip()
        ]
        region_results = map_account_regions(
            caller_identity_by_region,
            accounts=accounts,
            regions=regions,
            auth=auth,
            max_workers=args.max_workers,
        )
        problems.extend(
            verify_outcomes(
                outcomes(region_results),
                expected_failures=expected_failures,
                expected_role=auth.name,
            )
        )
        expected_pairs = [
            (account.id, region) for account in accounts for region in regions
        ]
        observed_pairs = [
            (result.account.id, result.region) for result in region_results
        ]
        if observed_pairs != expected_pairs:
            problems.append("Region results lost input order or membership")
        report["region_summary"] = region_results.summary()
        report["region_results"] = region_results.to_dicts()
        print(
            f"regions:  {region_results.success_count} ok, "
            f"{region_results.failure_count} failed"
        )

    if args.discover_regions:
        discovered = map_account_regions(
            caller_identity_by_region,
            accounts=accounts,
            auth=auth,
            discover_regions=True,
            max_workers=args.max_workers,
        )
        problems.extend(
            verify_outcomes(
                outcomes(discovered),
                expected_failures=expected_failures,
                expected_role=auth.name,
            )
        )
        report["discovery_summary"] = discovered.summary()
        report["discovery_results"] = discovered.to_dicts()
        print(
            f"discover: {discovered.success_count} ok, "
            f"{discovered.failure_count} failed"
        )

    report["problems"] = problems
    report["passed"] = not problems
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    if args.report is not None:
        args.report.write_text(
            json.dumps(report, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"report:   {args.report}")

    if problems:
        print("VALIDATION FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
