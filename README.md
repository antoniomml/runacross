# RunAcross

[![CI](https://github.com/antoniomml/runacross/actions/workflows/ci.yml/badge.svg)](https://github.com/antoniomml/runacross/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/runacross.svg)](https://pypi.org/project/runacross/)

Concurrent Python execution across AWS accounts and Regions.

RunAcross authenticates into each account, runs your callback concurrently,
isolates errors, and aggregates results so your code can focus on the AWS
operation itself. Authentication is pluggable: assume an IAM role in every
account, or use named AWS CLI / IAM Identity Center profiles.

**1.0.0rc1** is an opt-in release candidate with the same
runtime code as 0.7.0. Normal installation selects 0.7.0; install the candidate
explicitly with `python -m pip install runacross==1.0.0rc1`.
The [public contract](docs/api.md) and [readiness record](docs/readiness-1.0.md)
describe the proposed compatibility commitments and remaining validation.

[Quickstart](#quickstart) · [API](docs/api.md) · [Examples](examples/README.md) ·
[Operational guide](docs/operations.md) · [Contributing](CONTRIBUTING.md)

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

Callbacks must be synchronous. `async def` callbacks and observers are rejected;
return ordinary values rather than awaitables or async generators.

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

Pass `verify_account_id=True` to call `sts:GetCallerIdentity` after the
profile credentials resolve and fail authentication when the returned
Account does not match the target:

```python
Profile("AWS-Infosec-{account_id}", verify_account_id=True)
```

This is off by default so the ordinary path does not add an extra STS call.
Each result exposes the resolved `profile_name` or `role_name` without
credentials.

`Profile` does not discover accounts automatically, RunAcross does not run
`aws sso login`, and one execution cannot mix Role and Profile. Configure the
strategy in your application:

```python
import os
from runacross import Profile, Role


def auth():
    if os.environ.get("RUNACROSS_ROLE_NAME"):
        return Role(os.environ["RUNACROSS_ROLE_NAME"])
    return Profile(os.environ["RUNACROSS_PROFILE_PATTERN"])
```

## Account sources

Discovery and execution stay as two steps, so you can inspect or filter
accounts before any callback runs:

```python
accounts = list_accounts(...)
results = map_accounts(callback, accounts=accounts, auth=...)
```

| | `runacross.profiles.list_accounts()` | `runacross.organizations.list_accounts()` |
| --- | --- | --- |
| Reads | Local `~/.aws/config` (including `AWS_CONFIG_FILE`) | AWS Organizations `ListAccounts` |
| Network | No, unless the optional organization guard is used | Yes |
| Returns | Profiles attached to one named `sso_session` | Accounts whose current `State` is `ACTIVE` |
| Freshness | Configured targets; can include closed accounts or stale assignments | Live organization inventory |
| Permissions | None locally; `organizations:DescribeOrganization` if you pass the guard | `organizations:ListAccounts`; `DescribeOrganization` with the ID guard; `ListAccountsForParent` and `ListOrganizationalUnitsForParent` with `parent_id` |

You can also pass account IDs or `Account` objects from a file, API, or your
own inventory. See [examples/README.md](examples/README.md) for short scripts.

### Identity Center profiles

When the shared AWS config is the source of the account list, discover only
profiles attached to one named SSO session:

```python
from runacross import Profile, map_accounts
from runacross.profiles import list_accounts

accounts = list_accounts(
    pattern="AWS-Infosec-{account_id}",
    sso_session="control-tower",
    limit=3,
)

results = map_accounts(
    who_am_i,
    accounts=accounts,
    auth=Profile("AWS-Infosec-{account_id}"),
)
```

`sso_session` is required so profiles from different Identity Center sessions
cannot be combined accidentally. The profile name must match the pattern
exactly, and its captured account ID must equal `sso_account_id`.

Optionally validate the expected AWS Organization using one profile from the
selected SSO session. The guard calls only `DescribeOrganization`, not
`ListAccounts`:

```python
accounts = list_accounts(
    pattern="AWS-Infosec-{account_id}",
    sso_session="control-tower",
    organization_id="o-exampleorgid",
    organization_profile="AWSAdministratorAccess-999999999999",
)
```

Both organization arguments must be supplied together, and the validation
profile must reference the selected `sso_session`.

### AWS Organizations

Organizations is an optional, explicit source of the live account inventory:

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

To list accounts under a root or OU instead of the whole organization:

```python
accounts = list_accounts(
    organization_id="o-exampleorgid",
    parent_id="ou-exampleroot-workloads",
)
```

Nested OUs are included by default. Pass `include_nested=False` for direct
children only. Filter or inspect the returned list before `map_accounts`.
Invalid IDs and organization mismatches raise `ConfigError`.

Call `list_accounts()` without an ID when that guard is not needed.
Discovered `Account` objects include the Organizations name and root email
address; treat those fields as sensitive. `Account` redacts the email in
`repr()` output, but the value remains on the object.

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

## Filters

Both executors accept `exclude_accounts`. `map_account_regions` also accepts
`exclude_regions`. Filters preserve input order and do not silently deduplicate.
Both discovery helpers accept `limit=` to keep the first matching accounts
instead of slicing the list by hand. `limit=0` returns an empty list without
reading AWS configuration, resolving credentials, or making AWS calls (including
the optional organization guard). `None` means no limit.

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
named `assume_role`. Failed results also expose `result.error_code` when the
stored exception is a Botocore `ClientError`; RunAcross does not parse
exception text and does not store credentials. `result.profile_name` and
`result.role_name` identify which profile or role was selected.

`RunResults` and `RegionResults` preserve input order and provide:

```python
results.successful
results.failed
results.success_count
results.failure_count
results.failures_by_phase()
results.summary()
results.to_dicts()
```

`to_dicts()` is conversion, not printing. Use it for JSON, CSV, logging, or
your own reports:

```python
import json

print(json.dumps(results.summary()))
print(json.dumps(results.to_dicts(), indent=2))
```

Serialized records include account IDs and optional names, not Organizations
email addresses. Callback return values are included as-is; encode them in
your application if they are not JSON-serializable.

Use `result.unwrap()` when code wants the typed value or the stored exception.

RunAcross does not retry the callback because arbitrary functions may not be
idempotent. Botocore may still retry individual AWS requests on clients that
RunAcross or your callback create.

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

## Progress

`map_accounts` and `map_account_regions` still wait for every target and
return results in input order. Pass `on_result` to observe each completion
as it happens:

```python
from runacross import show_progress

results = map_accounts(
    who_am_i,
    accounts=accounts,
    auth=Profile("AWS-Infosec-{account_id}"),
    on_result=show_progress(),
)
```

`show_progress()` rewrites one status line on stderr when that stream is a
TTY:

```text
runacross  47/186  ok 44  auth 2  worker 1  111122223333
```

In CI, pipes, and Lambda it stays silent. It is not a tqdm or rich
integration; those tools can consume the same callback:

```python
def on_result(result, *, completed, total):
    log.info("%s %s/%s", result.account.id, completed, total)


results = map_accounts(..., on_result=on_result)
```

An exception from `on_result` stops new submissions, cancels work that has not
started, waits for running callbacks, and then propagates to the caller.
It cannot undo AWS operations that have already started. With `discover_regions=True`,
discovery authentication failures are reported first, then worker completions.

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
Listing under a root or OU needs `organizations:ListAccountsForParent`, and
nested OUs also need `organizations:ListOrganizationalUnitsForParent`.
Enabled-Region discovery needs `account:ListRegions`.

For `Profile`, the Identity Center permission set (or other profile identity)
needs only the service permissions used by the callback. Local profile
discovery needs no AWS permissions. Its optional organization guard needs
`organizations:DescribeOrganization` on `organization_profile`, but does not
need `organizations:ListAccounts`.

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
configures it. RunAcross logs target IDs, Regions, phases, and durations, but
does not log exception messages or tracebacks. Results retain the original
errors and callback values; treat those as application data that may contain
secrets, including when exporting with `to_dicts()`.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Examples

Minimal scripts live in [examples/](examples/):

- AssumeRole: [examples/caller_identity.py](examples/caller_identity.py)
- Identity Center profiles: [examples/identity_center_profiles.py](examples/identity_center_profiles.py)
- Organizations discovery: [examples/organization_accounts.py](examples/organization_accounts.py)
- Account and Region execution: [examples/ec2_inventory.py](examples/ec2_inventory.py)
- Result export: [examples/export_results.py](examples/export_results.py)

## Public API

The supported surface is the names in `runacross.__all__` plus:

- `runacross.profiles.list_accounts`
- `runacross.organizations.list_accounts`
- `runacross.regions.list_enabled_regions`

Everything else, including `runacross.sts` and helpers in `runacross.models`
that are not re-exported, is internal and may change without a deprecation.
See [docs/api.md](docs/api.md).

## Roadmap

The current priority is reliability, compatibility, and measurable execution
overhead. Larger selectors and timeout APIs need evidence from real usage.
The default path stays two calls and a callback. See [docs/roadmap.md](docs/roadmap.md)
and the [September 2026 audit](docs/audit-2026-09.md).

## Contributing

Development uses pytest, Ruff, and mypy. See
[CONTRIBUTING.md](CONTRIBUTING.md).

RunAcross is licensed under the Apache License 2.0.
