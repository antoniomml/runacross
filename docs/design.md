# RunAcross design

## Problem

AWS automation across many accounts repeatedly rebuilds the same machinery:
validate accounts, assume a role, create Boto3 sessions, schedule concurrent
work, isolate failures, and aggregate results. That plumbing obscures the AWS
operation the program is meant to perform.

RunAcross turns the pattern into one synchronous Python primitive:

```text
accounts -> futures -> AssumeRole -> Session -> callback -> results
```

## Goals

- Execute an arbitrary synchronous Python callback once per AWS account.
- Accept account IDs or richer `Account` objects.
- Use the standard Boto3 credential chain, with an optional source Session.
- Isolate AssumeRole and callback failures by account.
- Preserve input order while executing concurrently.
- Preserve the callback return type as `RunResults[T]`.
- Remain useful in scripts, CI, containers, EC2, ECS, and Lambda.
- Keep the runtime dependency set and public API small.

## Non-goals

RunAcross is not a scanner, CSPM, resource inventory, policy engine,
credential store, workflow scheduler, CLI, or infrastructure deployment
system. Version 0.1 does not provide async execution, multiprocessing,
multi-Region fan-out, callback retries, hard timeouts, fail-fast behavior,
automatic credential refresh, or advanced Organizations selectors.

## Public API

```python
from runacross import Account, RunResults, map_accounts


def worker(session, account: Account) -> str:
    sts = session.client("sts")
    return sts.get_caller_identity()["Arn"]


results: RunResults[str] = map_accounts(
    worker,
    accounts=[
        "111111111111",
        Account(id="222222222222", name="Development"),
    ],
    role_name="SecurityAuditRole",
    role_session_name="runacross",
    max_workers=10,
)
```

The initial signature is:

```python
def map_accounts(
    function: Callable[[boto3.Session, Account], T],
    *,
    accounts: Iterable[str | Account],
    role_name: str,
    role_session_name: str = "runacross",
    external_id: str | None = None,
    duration_seconds: int | None = None,
    source_session: boto3.Session | None = None,
    botocore_config: Config | None = None,
    max_workers: int = 10,
) -> RunResults[T]: ...
```

`role_name` may contain an IAM role path. Role ARN construction is isolated
internally and uses the STS client's partition. A public role ARN resolver is
not needed in 0.1, but this boundary leaves room for one later.

Account strings are converted to immutable `Account` values. Account IDs must
contain exactly 12 ASCII digits. Inputs are not silently deduplicated.
`Account.__repr__` redacts `email` when that field is present.

`AccountResult[T]` contains the account, value or exception, elapsed duration,
and failure phase. `ExecutionPhase` distinguishes `assume_role` from `worker`.
`success` is based on the absence of an error, so a callback may successfully
return `None`.

`RunResults[T]` is an immutable `Sequence` preserving input order. It exposes
`successful`, `failed`, `success_count`, and `failure_count`.

## Execution model

`map_accounts` performs global validation before starting work. Invalid account
IDs, role session names, worker counts, or other global configuration errors
are raised directly.

For non-empty input:

1. Create or accept the source Boto3 Session in the calling thread.
2. Reject a source Session that has no Region.
3. Create one low-level STS client before opening the pool.
4. Submit one task per account to `ThreadPoolExecutor`.
5. Each task calls AssumeRole through the shared STS client.
6. The task creates a new Boto3 Session from the temporary credentials.
7. The task calls `function(session, account)` in the same worker thread.
8. The calling thread consumes futures with `as_completed`.
9. Results are placed into their original input positions.

Empty input returns an empty `RunResults` without resolving credentials or
creating AWS clients.

## Concurrency

AWS SDK calls are normally I/O-bound, making `ThreadPoolExecutor` a simpler fit
than multiprocessing or asyncio. The explicit default of 10 avoids Python's
version-dependent, CPU-derived default. Users can lower or raise the value
based on workload, service quotas, and environment limits.

Boto3 Sessions and Resources are not shared. The source Session is used only
to create the STS client before concurrency begins. Low-level clients are
generally thread-safe; custom Botocore event hooks can invalidate that
assumption. Each callback receives a Session unique to its account task.

RunAcross does not expose the executor or implement a scheduler. It waits for
all submitted work before returning.

## Error isolation

Ordinary exceptions from AssumeRole and the callback become failed
`AccountResult` values. A failed account does not cancel pending or running
accounts. `KeyboardInterrupt`, `SystemExit`, and other `BaseException`
subclasses are not converted into account failures.

The original exception type and message remain inspectable. RunAcross clears
retained traceback frames before returning failures so results do not keep
Sessions and temporary credentials alive through frame locals. Full tracebacks
are available through DEBUG logging at the point of failure.

RunAcross does not retry an arbitrary callback. Botocore may retry individual
AWS requests according to each client's configuration.

## Authentication and STS

With no `source_session`, RunAcross creates `boto3.Session()` and therefore
inherits the normal credential provider chain. A caller can supply a configured
Session, for example one using an AWS profile.

RunAcross sends `ExternalId` only when provided. `DurationSeconds` is omitted
unless `duration_seconds` is supplied; valid values are 900-43200 seconds and
remain subject to the target role's maximum session duration. The default role
session name is the predictable value `runacross`; callers whose trust policies
require a specific value can override it. No credentials are returned or
persisted, and RunAcross does not deliberately add them to logs. Callback
exception messages are user-controlled and must not contain secrets.

The source Session must have a Region; `map_accounts` raises `ValueError`
before creating clients if it does not. The target Session inherits that
Region. Temporary credentials are not refreshable in 0.1 and expire after the
assumed session lifetime.

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

Version 0.1 invokes the callback once per account. Multi-Region execution will
use a separate function, provisionally `map_account_regions`, rather than
adding `regions` to `map_accounts`. A separate function keeps callback arity,
result identity, and Cartesian-product behavior explicit.

Future enabled-Region discovery must query AWS rather than relying only on
Boto3 endpoint metadata. It is not required by the initial account primitive.

