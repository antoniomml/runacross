# RunAcross design

## Problem

AWS automation across many accounts repeatedly rebuilds the same machinery:
validate accounts, authenticate, create Boto3 sessions, schedule concurrent
work, isolate failures, and aggregate results. That plumbing obscures the AWS
operation the program is meant to perform.

RunAcross turns the pattern into synchronous Python primitives:

```text
accounts -> Role or Profile -> Session -> callback -> results
accounts x regions -> Role or Profile -> Session -> callback -> results
```

## Goals

- Execute an arbitrary synchronous Python callback once per AWS account, or
  once per account and Region pair.
- Accept account IDs or richer `Account` objects.
- Authenticate through `Role` (STS AssumeRole) or `Profile` (named AWS CLI /
  IAM Identity Center profiles), without teaching the callback which was used.
- Use the standard Boto3 credential chain, with an optional source Session on
  `Role`.
- Isolate authentication and callback failures by target.
- Preserve input order while executing concurrently.
- Preserve the callback return type as `RunResults[T]` or `RegionResults[T]`.
- Remain useful in scripts, CI, containers, EC2, ECS, and Lambda.
- Keep the runtime dependency set and public API small.

## Non-goals

RunAcross is not a scanner, CSPM, resource inventory, policy engine,
credential store, workflow scheduler, CLI, or infrastructure deployment
system. It does not guess profiles from `~/.aws/config`, run `aws sso login`,
or mix Role and Profile in a single execution. Version 0.2 does not provide
async execution, multiprocessing, callback retries, hard timeouts, fail-fast
behavior, automatic credential refresh, or advanced Organizations selectors.

## Public API

```python
from runacross import Account, Profile, Role, RunResults, map_accounts
from runacross import map_account_regions


def worker(session, account: Account) -> str:
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


results: RunResults[str] = map_accounts(
    worker,
    accounts=[
        "111111111111",
        Account(id="222222222222", name="Development"),
    ],
    auth=Role("SecurityAuditRole"),
)
```

`map_accounts` accepts either `auth=` or the 0.1 shortcut `role_name=`:

```python
def map_accounts(
    function: Callable[[boto3.Session, Account], T],
    *,
    accounts: Iterable[str | Account],
    auth: Role | Profile | None = None,
    role_name: str | None = None,
    role_session_name: str = "runacross",
    external_id: str | None = None,
    duration_seconds: int | None = None,
    source_session: boto3.Session | None = None,
    botocore_config: Config | None = None,
    max_workers: int = 10,
    exclude_accounts: Iterable[str | Account] = (),
) -> RunResults[T]: ...
```

`Role.name` may contain an IAM role path. Role ARN construction is isolated
internally and uses the STS client's partition.

`Profile` requires exactly one of `pattern`, `mapping`, or `resolver`.
Patterns may use `{account_id}` and `{name}`.

Account strings are converted to immutable `Account` values. Account IDs must
contain exactly 12 ASCII digits. Inputs are not silently deduplicated.
`Account.__repr__` redacts `email` when that field is present.

`AccountResult[T]` contains the account, value or exception, elapsed duration,
and failure phase. `ExecutionPhase` distinguishes `auth` from `worker`.
`success` is based on the absence of an error, so a callback may successfully
return `None`. Version 0.1 used `assume_role` for the authentication phase.

`RunResults[T]` is an immutable `Sequence` preserving input order. It exposes
`successful`, `failed`, `success_count`, and `failure_count`.

`map_account_regions` uses a three-argument callback and `RegionResults[T]`.
Each item is an `AccountRegionResult` whose identity is `AccountRegion`.

```python
def map_account_regions(
    function: Callable[[boto3.Session, Account, str], T],
    *,
    accounts: Iterable[str | Account],
    auth: Role | Profile | None = None,
    role_name: str | None = None,
    regions: Iterable[str] | None = None,
    exclude_accounts: Iterable[str | Account] = (),
    exclude_regions: Iterable[str] = (),
    discover_regions: bool = False,
    ...
) -> RegionResults[T]: ...
```

Explicit `regions` produce a Cartesian product (accounts outer, Regions
inner). `discover_regions=True` lists enabled Regions per account after
authentication. Combining both treats `regions` as an allowlist on the
discovered set.

## Execution model

`map_accounts` and `map_account_regions` perform global validation before
starting work. Invalid account IDs, Region names, role session names, worker
counts, or other global configuration errors are raised directly.

For non-empty input:

1. Resolve `auth` (`Role`/`Profile`, or `role_name=` as a `Role`).
2. Apply `exclude_accounts` (and `exclude_regions` when present).
3. Bind authentication in the calling thread (`Role` creates the shared STS
   client here and rejects a source Session with no Region).
4. For Region discovery, authenticate per account and call Account Management
   `ListRegions` before submitting worker tasks.
5. Submit one task per remaining target to `ThreadPoolExecutor`.
6. Each task obtains a Session from the bound auth. `Role` assumes once per
   account and copies credentials into a per-task Session for the target
   Region.
7. The task calls `function(session, account)` or
   `function(session, account, region)` in the same worker thread.
8. The calling thread consumes futures with `as_completed`.
9. Results are placed into their original input positions.

Empty input after filters returns an empty result collection without resolving
credentials or creating AWS clients.

## Concurrency

AWS SDK calls are normally I/O-bound, making `ThreadPoolExecutor` a simpler fit
than multiprocessing or asyncio. The explicit default of 10 avoids Python's
version-dependent, CPU-derived default. Users can lower or raise the value
based on workload, service quotas, and environment limits.

Boto3 Sessions and Resources are not shared. Each callback receives a Session
unique to its task. The source Session on `Role` is used only to create the
STS client before concurrency begins. Low-level clients are generally
thread-safe; custom Botocore event hooks can invalidate that assumption.

RunAcross does not expose the executor or implement a scheduler. It waits for
all submitted work before returning.

## Error isolation

Ordinary exceptions from authentication and the callback become failed result
values. A failed target does not cancel pending or running targets.
`KeyboardInterrupt`, `SystemExit`, and other `BaseException` subclasses are
not converted into account failures.

The original exception type and message remain inspectable. RunAcross clears
retained traceback frames before returning failures so results do not keep
Sessions and temporary credentials alive through frame locals. Full tracebacks
are available through DEBUG logging at the point of failure.

RunAcross does not retry an arbitrary callback. Botocore may retry individual
AWS requests according to each client's configuration.

## Authentication

`Role` uses `boto3.Session()` when no `source_session` is provided and
therefore inherits the normal credential provider chain. A caller can supply a
configured Session, for example one using an AWS profile.

`Profile` constructs `boto3.Session(profile_name=...)` per account. Missing
profiles, expired IAM Identity Center sessions, and profiles without a Region
are per-account `auth` failures.

`Role` sends `ExternalId` only when provided. `DurationSeconds` is omitted
unless `duration_seconds` is supplied; valid values are 900-43200 seconds and
remain subject to the target role's maximum session duration. The default role
session name is the predictable value `runacross`; callers whose trust policies
require a specific value can override it. No credentials are returned or
persisted, and RunAcross does not deliberately add them to logs. Callback
exception messages are user-controlled and must not contain secrets.

Temporary credentials copied into a new Boto3 Session do not refresh
automatically. They expire after the assumed session lifetime.

RunAcross-owned clients use Botocore standard retries with three total attempts.
A provided `botocore_config` is merged with the library defaults and takes
precedence. The default connection pool is sized to at least the worker count,
unless the user explicitly overrides it with a smaller value. Configuration
does not propagate to clients created later by the callback.

## Organizations

Organizations is an optional account source:

```python
from runacross.organizations import list_accounts

accounts = list_accounts(organization_id="o-exampleorgid")
results = map_accounts(worker, accounts=accounts, role_name="SecurityAuditRole")
```

The function call makes network activity explicit. It uses the Organizations
paginator and returns only accounts whose current `State` is `ACTIVE`.
`exclude_accounts` provides a small safety filter.

The optional organization ID is not a selector. AWS chooses the organization
from the credentials. RunAcross calls `DescribeOrganization` and rejects a
mismatch before listing accounts.

Discovery and execution remain separate so the core can operate without AWS
Organizations and account lists can come from files, APIs, configuration, or
other systems.

## Regions

`map_accounts` invokes the callback once per account. Multi-Region execution
uses `map_account_regions` rather than adding `regions` to `map_accounts`. A
separate function keeps callback arity, result identity, and Cartesian-product
behavior explicit.

Enabled-Region discovery uses Account Management `ListRegions` and treats
`ENABLED` and `ENABLED_BY_DEFAULT` as usable. Boto3 endpoint metadata alone
does not describe which Regions an account has enabled.
`list_enabled_regions()` exposes that query for callers who want to choose
Regions before execution.
