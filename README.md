# RunAcross

[![CI](https://github.com/antoniomml/runacross/actions/workflows/ci.yml/badge.svg)](https://github.com/antoniomml/runacross/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/runacross.svg)](https://pypi.org/project/runacross/)

Concurrent Python execution across AWS accounts.

RunAcross handles STS AssumeRole, concurrent execution, error isolation and
result aggregation so your code can focus on the AWS operation itself.

> RunAcross 0.1 executes across accounts. Account-by-Region execution is
> planned for a later release.

## Why RunAcross?

Multi-account scripts repeatedly need the same plumbing:

```text
accounts
-> STS AssumeRole
-> boto3 Session
-> ThreadPoolExecutor
-> callback
-> isolated errors
-> aggregated results
```

RunAcross packages that pattern as a small synchronous function. It is a
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

```python
from runacross import map_accounts


def who_am_i(session, account):
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


results = map_accounts(
    who_am_i,
    accounts=[
        "111111111111",
        "222222222222",
    ],
    role_name="SecurityAuditRole",
    max_workers=10,
)

for result in results:
    if result.success:
        print(f"{result.account.id}: {result.value}")
    else:
        print(f"{result.account.id}: {result.phase}: {result.error}")
```

Account IDs are converted to immutable `Account` objects. You can also provide
metadata explicitly:

```python
from runacross import Account

accounts = [
    Account(id="111111111111", name="Production"),
    Account(id="222222222222", name="Development"),
]
```

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

## Handling failures

One failed account does not cancel the others:

```python
for result in results:
    if result.success:
        use(result.value)
    elif result.phase == "assume_role":
        report_access_problem(result.account, result.error)
    else:
        report_worker_problem(result.account, result.error)
```

`RunResults` preserves input order and provides:

```python
results.successful
results.failed
results.success_count
results.failure_count
```

Use `result.unwrap()` when code wants the typed value or the stored exception:

```python
for result in results:
    try:
        value = result.unwrap()
    except Exception as error:
        handle(result.account, error)
```

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

This configuration applies only to clients RunAcross creates, such as STS.
Pass a `Config` to clients created inside your callback to configure their
retries.

## Authentication

By default, RunAcross uses `boto3.Session()` and the standard Boto3 credential
provider chain. It works with configured environment credentials, profiles,
IAM Identity Center, web identity, ECS task roles, EC2 instance profiles,
Lambda execution roles, and GitHub Actions OIDC.

You can provide a source Session:

```python
import boto3

source_session = boto3.Session(profile_name="security")

results = map_accounts(
    who_am_i,
    accounts=accounts,
    role_name="SecurityAuditRole",
    source_session=source_session,
)
```

The source Session must have a Region. RunAcross copies it onto each assumed
Session and raises `ValueError` before calling STS if it is missing. Configure
`AWS_DEFAULT_REGION`, the profile's region, or `boto3.Session(region_name=...)`.

The target role must trust the source identity, and the source identity must
be allowed to call `sts:AssumeRole`.

Assumed Sessions in 0.1 do not refresh automatically. Callbacks should finish
within the STS session lifetime, which defaults to one hour. Pass
`duration_seconds` (900-43200, still subject to the role maximum) to request a
shorter or longer session:

```python
results = map_accounts(
    who_am_i,
    accounts=accounts,
    role_name="SecurityAuditRole",
    duration_seconds=900,
)
```

## IAM permissions

The source identity needs `sts:AssumeRole` for the target roles. Organizations
discovery additionally needs `organizations:ListAccounts`; using the
organization ID guard also needs `organizations:DescribeOrganization`.

The assumed role needs only the service permissions used by the callback.
See [docs/iam.md](docs/iam.md) for restrictive examples and trust-policy
requirements.

## Running in AWS Lambda

Lambda execution-role credentials are discovered automatically. Package
RunAcross and its Boto3 dependency with the function or in a layer so the
versions are controlled by your deployment.

All callbacks must finish before the handler returns. Do not leave RunAcross
work running in the background between Lambda invocations. Tune `max_workers`
for the function's memory, timeout, and downstream AWS quotas.

## Security

RunAcross does not persist or return STS credentials, add telemetry, or create
non-AWS service clients. Library logging is silent unless the application
configures it. RunAcross never deliberately adds credentials to logs, but
callback exception messages are emitted at DEBUG and must not contain secrets.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Roadmap

Planned areas include explicit account-by-Region execution, enabled-Region
discovery, and small Organizations filters. RunAcross will remain a library
primitive rather than becoming an orchestration framework.

See [docs/roadmap.md](docs/roadmap.md).

## Contributing

Development uses pytest, Ruff, and mypy. See
[CONTRIBUTING.md](CONTRIBUTING.md).

RunAcross is licensed under the Apache License 2.0.

