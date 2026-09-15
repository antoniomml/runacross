"""Read-only live validation of Profile authentication for the 1.0 candidate.

Run this script manually from an editable or installed environment against
disposable or read-only AWS accounts:

    python validation/profile_consumer.py \
        --account 111111111111 \
        --account 222222222222 \
        --pattern 'AWS-Infosec-{account_id}' \
        --verify-account-id \
        --regions eu-west-1 \
        --report profile-report.json

Accounts can also come from local Identity Center profiles:

    python validation/profile_consumer.py \
        --sso-session control-tower \
        --pattern 'AWS-Infosec-{account_id}' \
        --limit 3 \
        --report profile-discovery-report.json

The script performs only read-only ``sts:GetCallerIdentity`` calls (plus the
optional ``--verify-account-id`` check inside the auth phase). It exits
non-zero when a target fails, when an identity or profile does not match its
target, or when an expected authentication failure is missing.
"""

from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import botocore
from boto3.session import Session

from runacross import (
    Account,
    ExecutionPhase,
    Profile,
    RegionResults,
    RunResults,
    __version__,
    map_account_regions,
    map_accounts,
)
from runacross.models import AccountRegionResult, AccountResult
from runacross.profiles import list_accounts

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
    expected_profiles: Mapping[str, str],
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
        expected = expected_profiles.get(account_id)
        if result.profile_name != expected:
            problems.append(
                f"{label}: profile metadata {result.profile_name!r}, "
                f"expected {expected!r}"
            )
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
        metavar="ID",
        help="target account ID (repeatable); omit when using --sso-session",
    )
    strategy = command.add_mutually_exclusive_group(required=True)
    strategy.add_argument(
        "--pattern",
        metavar="PATTERN",
        help="profile pattern such as AWS-Infosec-{account_id}",
    )
    strategy.add_argument(
        "--mapping-json",
        metavar="JSON",
        help=(
            "JSON object mapping account IDs to profile names, such as "
            '\'{"111111111111": "prod-security"}\''
        ),
    )
    command.add_argument(
        "--sso-session",
        default=None,
        help="discover accounts locally from this named SSO session",
    )
    command.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum accounts to keep during local discovery",
    )
    command.add_argument(
        "--verify-account-id",
        action="store_true",
        help="call sts:GetCallerIdentity during the auth phase",
    )
    command.add_argument(
        "--regions",
        default=None,
        help="comma-separated Regions for account-by-Region execution",
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


def build_auth(args: argparse.Namespace) -> Profile:
    """Create the Profile strategy described by the command line."""

    verify = bool(args.verify_account_id)
    if args.pattern is not None:
        return Profile(pattern=str(args.pattern), verify_account_id=verify)
    try:
        mapping = json.loads(str(args.mapping_json))
    except json.JSONDecodeError as error:
        raise SystemExit(f"--mapping-json is not valid JSON: {error}") from error
    if not isinstance(mapping, dict):
        raise SystemExit("--mapping-json must be a JSON object")
    return Profile(mapping=mapping, verify_account_id=verify)


def main(argv: Sequence[str] | None = None) -> int:
    command = parser()
    args = command.parse_args(argv)
    expected_failures = frozenset(str(value) for value in args.expect_failure)

    if args.sso_session is not None:
        if args.mapping_json is not None:
            command.error("--sso-session requires --pattern")
        if args.account:
            command.error("pass either --account or --sso-session, not both")
        accounts = list_accounts(
            pattern=str(args.pattern),
            sso_session=str(args.sso_session),
            limit=args.limit,
        )
    else:
        if not args.account:
            command.error("pass --account (repeatable) or --sso-session")
        try:
            accounts = [Account(id=value) for value in args.account]
        except (TypeError, ValueError) as error:
            command.error(f"invalid --account: {error}")

    problems: list[str] = []
    if not accounts:
        problems.append("no accounts to validate")

    try:
        auth = build_auth(args)
    except (TypeError, ValueError) as error:
        command.error(f"cannot configure Profile authentication: {error}")
    expected_profiles: dict[str, str] = {}
    for account in accounts:
        if account.id in expected_failures:
            continue
        try:
            expected_profiles[account.id] = auth.profile_name(account)
        except (KeyError, ValueError) as error:
            problems.append(f"{account.id}: cannot resolve profile name: {error}")
    report: dict[str, Any] = {
        "environment": environment(),
        "auth": "Profile",
        "pattern": args.pattern,
        "sso_session": args.sso_session,
        "accounts": [account.id for account in accounts],
        "expected_profiles": expected_profiles,
        "expected_failures": sorted(expected_failures),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    if accounts:
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
                expected_profiles=expected_profiles,
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

    if args.regions and accounts:
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
                expected_profiles=expected_profiles,
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
