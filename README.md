# RunAcross

[![CI](https://github.com/antoniomml/runacross/actions/workflows/ci.yml/badge.svg)](https://github.com/antoniomml/runacross/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/runacross.svg)](https://pypi.org/project/runacross/)

Concurrent Python execution across AWS accounts and Regions.

RunAcross authenticates into each account, runs your callback concurrently,
isolates errors, and aggregates results so your code can focus on the AWS
operation itself. Authentication is pluggable: assume an IAM role in every
account, or use named AWS CLI / IAM Identity Center profiles.

## Why RunAcross?

Multi-account scripts repeatedly need the same plumbing:

```text
accounts
-> Role or Profile
-> boto3 Session
-> ThreadPoolExecutor
-> callback
-> isolated errors
-> aggregated results
```

RunAcross packages that pattern as small synchronous functions. It is a
library primitive, not a scanner, CLI, scheduler, or credentials manager.

## Installation

```bash
pip install runacross
```

RunAcross requires Python 3.10 or later. For development from a local clone:

```bash
python -m pip install -e ".[dev]"
```

## Quickstart

Write a function for **one** account. RunAcross runs it in many:

```python
from runacross import map_accounts


def who_am_i(session, account):
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


results = map_accounts(
    who_am_i,
    accounts=["111111111111", "222222222222"],
    role_name="SecurityAuditRole",
)

for result in results:
    if result.success:
        print(f"{result.account.id}: {result.value}")
    else:
        print(f"{result.account.id}: {result.phase}: {result.error}")
```

`role_name=` is a shortcut for `auth=Role("SecurityAuditRole")`. Account IDs
are converted to immutable `Account` objects. You can also provide metadata
explicitly:

```python
from runacross import Account

accounts = [
    Account(id="111111111111", name="Production"),
    Account(id="222222222222", name="Development"),
]
```

## Authentication: Role and Profile

The callback never sees how the Session was obtained. Choose one strategy per
`map_accounts` / `map_account_regions` call.

### Role

Assume the same IAM role in each target account. This is the Organizations /
Lambda / CI pattern:

```python
import boto3
from runacross import Role, map_accounts

results = map_accounts(
    who_am_i,
    accounts=accounts,
    auth=Role(
        "SecurityAuditRole",
        source_session=boto3.Session(profile_name="security"),
        duration_seconds=900,
    ),
)
```

The source identity must be allowed to call `sts:AssumeRole`, and each target
role must trust that identity. `role_name=` on `map_accounts` still builds a
`Role` for compatibility with 0.1.

### Profile

Use named profiles from `~/.aws/config`, including IAM Identity Center
profiles. This is the laptop pattern after `aws sso login`:

```python
from runacross import Profile, map_accounts

results = map_accounts(
    who_am_i,
    accounts=["111111111111", "222222222222"],
    auth=Profile("{account_id}-script-SecurityAudit"),
)
```

If your profiles are named `111111111111-script-SecurityAudit`, that pattern
is enough. When names do not follow a convention, pass an explicit mapping or
a resolver:

```python
Profile(
    mapping={
        "111111111111": "prod-security",
        "222222222222": "dev-readonly",
    }
)

Profile(resolver=lambda account: f"sso-{account.id}")
```

Exactly one of `pattern`, `mapping`, or `resolver` is required. Pattern
placeholders are `{account_id}` and, if present on the `Account`, `{name}`.

RunAcross does not read your config to guess profiles, does not run
`aws sso login`, and does not mix Role and Profile in one call. Configure the
strategy in your application:

```python
import os
from runacross import Profile, Role


def auth():
    if os.environ.get("RUNACROSS_ROLE_NAME"):
        return Role(os.environ["RUNACROSS_ROLE_NAME"])
    return Profile(os.environ["RUNACROSS_PROFILE_PATTERN"])
```

## Account-by-Region execution

`map_accounts` calls the callback once per account. For a Cartesian product of
accounts and Regions, use `map_account_regions`. The callback receives the
Region as a third argument, and the Session is already set to that Region:

```python
from runacross import map_account_regions


def list_instance_ids(session, account, region):
    instance_ids = []
    paginator = session.client("ec2").get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            instance_ids.extend(
                instance["InstanceId"] for instance in reservation["Instances"]
            )
    return instance_ids


results = map_account_regions(
    list_instance_ids,
    accounts=["111111111111", "222222222222"],
    regions=["eu-west-1", "us-east-1"],
    role_name="SecurityAuditRole",
)

for result in results:
    if result.success:
        print(f"{result.account.id} {result.region}: {result.value}")
    else:
        print(f"{result.account.id} {result.region}: {result.phase}: {result.error}")
```

Each result has a structured identity, `result.target`, with `.account` and
`.region`. `Role` assumes the target role once per account and reuses those
credentials across Regions.

Pass `discover_regions=True` to list enabled Regions in each account with
Account Management `ListRegions` (`ENABLED` and `ENABLED_BY_DEFAULT` only).
An explicit `regions=` list then acts as an allowlist:

```python
from runacross.regions import list_enabled_regions

# Same Regions for every account, chosen by you:
#   regions=["eu-west-1", "us-east-1"]
#
# Whatever each account currently has enabled:
results = map_account_regions(
    list_instance_ids,
    accounts=accounts,
    role_name="SecurityAuditRole",
    discover_regions=True,
    exclude_regions=["ap-east-1"],
)

# Or discover from one Session outside the executor:
regions = list_enabled_regions()
```

`list_enabled_regions` queries AWS. It does not use Boto3 endpoint metadata.

## Using AWS Organizations

Organizations is an optional, explicit source of accounts:

```python
from runacross import map_accounts
from runacross.organizations import list_accounts

accounts = list_accounts(
    organization_id="o-exampleorgid",
    exclude_accounts=["111111111111"],
)

results = map_accounts(
    who_am_i,
    accounts=accounts,
    role_name="SecurityAuditRole",
)
```

The organization ID is a safety check, not a selector. AWS uses the source
credentials to determine which organization is visible. RunAcross verifies
that it matches the expected ID and then returns accounts whose current
Organizations `State` is `ACTIVE`.

Call `list_accounts()` without an ID when that guard is not needed.
Discovered `Account` objects include the Organizations name and root email
address; treat those fields as sensitive. `Account` redacts the email in
`repr()` output, but the value remains on the object.

See `examples/organization_accounts.py` for a complete discovery-plus-execution
script.

## Filters

Both executors accept `exclude_accounts`. `map_account_regions` also accepts
`exclude_regions`. Filters preserve input order and do not silently deduplicate.

```python
results = map_account_regions(
    list_instance_ids,
    accounts=accounts,
    regions=["eu-west-1", "us-east-1", "ap-southeast-2"],
    role_name="SecurityAuditRole",
    exclude_accounts=["111111111111"],
    exclude_regions=["ap-southeast-2"],
)
```

## Handling failures

One failed account or Region does not cancel the others:

```python
for result in results:
    if result.success:
        use(result.value)
    elif result.phase == "auth":
        report_access_problem(result.account, result.error)
    else:
        report_worker_problem(result.account, result.error)
```

`auth` covers role assumption and profile resolution. In 0.1 this phase was
named `assume_role`.

`RunResults` and `RegionResults` preserve input order and provide:

```python
results.successful
results.failed
results.success_count
results.failure_count
```

Use `result.unwrap()` when code wants the typed value or the stored exception.

RunAcross does not retry the callback because arbitrary functions may not be
idempotent.

## Concurrency

RunAcross uses `ThreadPoolExecutor`, which is suitable for the network-bound
work performed by Boto3. The default is 10 workers:

```python
results = map_accounts(
    who_am_i,
    accounts=accounts,
    role_name="SecurityAuditRole",
    max_workers=5,
)
```

More workers do not imply linear speedups. High concurrency can increase
throttling, connection use, memory use, and Lambda duration.

RunAcross-owned clients use Botocore standard retries with three total
attempts. Override them explicitly when needed:

```python
from botocore.config import Config

results = map_accounts(
    who_am_i,
    accounts=accounts,
    role_name="SecurityAuditRole",
    botocore_config=Config(
        retries={"mode": "adaptive", "total_max_attempts": 5},
    ),
)
```

This configuration applies only to clients RunAcross creates, such as STS or
the Account Management client used for Region discovery. Pass a `Config` to
clients created inside your callback to configure their retries.

## Source credentials

By default, `Role` uses `boto3.Session()` and the standard Boto3 credential
provider chain. It works with configured environment credentials, profiles,
IAM Identity Center, web identity, ECS task roles, EC2 instance profiles,
Lambda execution roles, and GitHub Actions OIDC.

Pass `source_session=` on `Role` (or on `map_accounts` when using `role_name=`)
to use a specific profile as the identity that assumes into every account.

The source Session must have a Region. RunAcross copies it onto each assumed
Session and raises `ValueError` before calling STS if it is missing. Configure
`AWS_DEFAULT_REGION`, the profile's region, or `boto3.Session(region_name=...)`.

`Profile` uses each named profile's own region unless `map_account_regions`
supplies a Region. Assumed Sessions do not refresh automatically. Callbacks
should finish within the STS session lifetime, which defaults to one hour.
Pass `duration_seconds` (900-43200, still subject to the role maximum) on
`Role` to request a shorter or longer session.

## IAM permissions

For `Role`, the source identity needs `sts:AssumeRole` for the target roles.
Organizations discovery additionally needs `organizations:ListAccounts`; using
the organization ID guard also needs `organizations:DescribeOrganization`.
Enabled-Region discovery needs `account:ListRegions`.

For `Profile`, the Identity Center permission set (or other profile identity)
needs only the service permissions used by the callback.

The assumed role, when using `Role`, needs only the service permissions used
by the callback. See [docs/iam.md](docs/iam.md) for restrictive examples and
trust-policy requirements.

## Running in AWS Lambda

Lambda execution-role credentials are discovered automatically. Package
RunAcross and its Boto3 dependency with the function or in a layer so the
versions are controlled by your deployment.

All callbacks must finish before the handler returns. Do not leave RunAcross
work running in the background between Lambda invocations. Tune `max_workers`
for the function's memory, timeout, and downstream AWS quotas. `Role` is the
usual Lambda strategy; local AWS CLI profiles are not available there.

## Security

RunAcross does not persist or return STS credentials, add telemetry, or create
non-AWS service clients. Library logging is silent unless the application
configures it. RunAcross never deliberately adds credentials to logs, but
callback exception messages are emitted at DEBUG and must not contain secrets.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Roadmap

Planned areas after 0.2 include lifecycle hooks, cooperative deadlines, and
richer Organizations selectors. RunAcross will remain a library primitive
rather than becoming an orchestration framework.

See [docs/roadmap.md](docs/roadmap.md).

## Contributing

Development uses pytest, Ruff, and mypy. See
[CONTRIBUTING.md](CONTRIBUTING.md).

RunAcross is licensed under the Apache License 2.0.
