# Public API

The public API is the contract covered by semantic versioning. Internal names
may change without a deprecation.

## Stable imports

```python
from runacross import (
    Account,
    AccountRegion,
    AccountRegionResult,
    AccountResult,
    ConfigError,
    ExecutionPhase,
    Profile,
    RegionResults,
    ResultCallback,
    Role,
    RunAcrossError,
    RunResults,
    __version__,
    map_account_regions,
    map_accounts,
    show_progress,
)
```

`runacross.__all__` is the authoritative top-level list. These submodule
functions are also public:

- `runacross.profiles.list_accounts`
- `runacross.organizations.list_accounts`
- `runacross.regions.list_enabled_regions`

`list_accounts` helpers accept `limit=` to return the first matching accounts.
`limit=0` returns `[]` after argument validation without reading config,
resolving credentials, or checking the organization guard. `None` is unlimited.
`organizations.list_accounts` also accepts `parent_id` for a root or OU, with
nested units included by default. `map_accounts` and `map_account_regions`
accept `on_result`. `show_progress()` returns a TTY-aware stderr reporter for
that callback. `Profile` accepts `verify_account_id=True` to confirm
`sts:GetCallerIdentity`. Discovery helpers raise `ConfigError` when the
request or inventory cannot be used.

## Executor contract

`map_accounts(function, *, accounts, auth=..., max_workers=10, ...)` calls
`function(session, account)`. `map_account_regions` calls
`function(session, account, region)` and additionally requires `regions=...`
or `discover_regions=True`. All options after `function` are keyword-only.
The full option lists and defaults are in [design.md](design.md).

- `accounts` accepts an iterable of 12-digit ID strings or `Account` objects.
  Region names are strings such as `eu-west-1`. Inputs are validated before
  authentication, preserve order, and are not silently deduplicated.
- Choose `auth=Role(...)` or `auth=Profile(...)`. The existing `role_name=`
  shortcut and associated role options remain supported, but cannot be mixed
  with `auth=`. An empty run still requires valid arguments and an auth choice.
- `max_workers` is a positive integer; booleans are rejected. `discover_regions`
  is a boolean. Empty account selections and empty explicit Region selections
  return empty results without binding authentication.
- Explicit Region output is account-major, then Region-input order. Discovery
  output is account-major, then the service's Region order after filtering.
  `regions=` with discovery filters enabled Regions; it does not reorder them.
  Discovery is a separate preparation phase before any worker callback runs.
- Every callback gets its own Session. Role credentials are reused per account
  within a run, but copied Role credentials do not refresh automatically.
  Profile resolvers run once per authentication attempt and must be thread-safe.
- Work completes before the call returns. Ordinary per-target exceptions become
  failed results and do not stop other targets. No callback is retried.

Callbacks and Profile resolvers must be synchronous. Recognizable coroutine
functions, async-generator functions, async callable objects, and partials of
those functions are rejected before authentication (at Profile construction for
resolvers). Inspectable signatures are checked for the required arguments.
Opaque extension callables without a signature are checked when invoked.

A synchronous wrapper that returns an awaitable or async generator is rejected
when its return value is inspected: worker wrappers produce `phase="worker"`
failures; resolver wrappers produce `phase="auth"` failures. Native coroutines
are closed without executing them. RunAcross does not start an event loop,
await values, or cancel caller-owned tasks. Other lazy values, including normal
generators, are returned as values and are not consumed. Materialize them inside
the callback if iteration errors should belong to that target.

## Result observers

```python
from runacross import AccountResult, ResultCallback


def report(result: AccountResult[int], *, completed: int, total: int) -> None:
    print(result.account.id, completed, total)


observer: ResultCallback[AccountResult[int]] = report
```

`on_result` receives the result positionally and `completed` / `total` as keyword
arguments. The first parameter's name is not prescribed. Account executors use
`AccountResult[T]`; regional executors use `AccountRegionResult[T]`.
`ResultCallback` is a contravariant typing protocol, not a runtime wrapper.

Observers run serially on the calling thread, as completed futures are consumed.
They run once per returned target, with `completed` increasing from 1 to `total`.
Simultaneous completions have no guaranteed relative order. An empty run emits
no observer calls. During discovery, failed preparations are reported first;
each contributes one failure result and one progress step. Successful discovery
with zero selected Regions contributes no result. Failures before a Region is
known use the Session/source Region, the first requested Region, or `us-east-1`
as a reporting label; that fallback is not evidence an AWS call ran there.

Observers must be synchronous and should return `None`. Ordinary return values
are ignored for compatibility; asynchronous returns raise `TypeError`.
Observer exceptions and `BaseException` subclasses stop new submissions,
cancel work that has not started, wait for running callbacks, and then propagate.
There is no partial result collection returned on that path. Already-started
AWS operations cannot be undone by interruption.

`show_progress(*, file=None, disable=None)` returns a compatible observer.
It writes to stderr on a TTY by default, is silent off-TTY, and accepts a boolean
override. Create a fresh reporter for each run. Custom observers can wrap logging,
tqdm, or other progress tools without adding those dependencies to RunAcross.

## Errors and validation

| Boundary | Behavior |
| --- | --- |
| Invalid call shape or checked argument type | `TypeError`, before authentication where detectable. |
| Invalid model/auth values, negative limits or worker counts | `ValueError`. |
| Discovery selectors, local discovery configuration or invalid inventory fields | `ConfigError`, a subclass of `RunAcrossError`. |
| AWS service failure in a standalone discovery helper | Original Botocore `ClientError` propagates. |
| Global authentication setup, such as a Role source without a Region | Exception propagates; no per-target results exist yet. |
| Per-target authentication, profile verification or Region discovery | Original exception stored with `ExecutionPhase.AUTH`. |
| Per-target callback invocation or invalid asynchronous return | Exception stored with `ExecutionPhase.WORKER`. |
| Observer failure, `KeyboardInterrupt`, `SystemExit` | Propagates after running work has been joined; not converted to a target failure. |

`RunAcrossError` does not include built-in `TypeError` / `ValueError` or all SDK
exceptions. `ConfigError` does not wrap per-target errors. Error types and phases
are part of the contract; exact human-readable message wording is not.

## Result conversion

`AccountResult` and `AccountRegionResult` expose `success`, `unwrap()`,
`phase`, `error_code`, `profile_name`, `role_name`, and `to_dict()`.
`error_code` is the Botocore `ClientError` code at
`response["Error"]["Code"]` when that value exists. `profile_name` and
`role_name` identify the selected profile or role and never include
credentials.

`RunResults` and `RegionResults` also expose `successful`, `failed`,
`success_count`, `failure_count`, `to_dicts()`, `failures_by_phase()`, and
`summary()`.

These helpers convert data. They do not print, write files, or choose a
report format. Serialized records include account IDs and optional names.
They omit the built-in Organizations email field and do not add authentication
credentials. Callback values and exception messages pass through unchanged and
may themselves contain sensitive data. Values must be JSON-compatible if the
caller plans to pass records to `json.dumps()`.

Collections preserve input order and support iteration, integer indexing, and
tuple slices. `successful` and `failed` return tuples; `summary()` reports
`total`, `success_count`, `failure_count`, and `failures_by_phase` with `auth` /
`worker` counts. This is shallow immutability: callback values and exception
objects may themselves be mutable. `unwrap()` returns `T`, including a valid
`None` result, or raises the original stored exception.

Exported records contain `account_id`, `account_name`, `profile_name`,
`role_name`, `success`, `value`, `error_type`, `error_message`, `error_code`,
`phase`, and `duration_seconds`; regional records add `region`. Missing metadata
is `None`. Successful records have no error or failure phase; failed records
have no value. Durations are finite, nonnegative seconds including that target's
authentication and callback time, not the time spent waiting to be submitted.
Result constructors validate account/target, error, phase, and duration types.

## Internal

Do not depend on `runacross.sts`, `runacross.executor`, `runacross.auth`
names other than `Role` and `Profile`, or `runacross.models` helpers that are
not re-exported. Names that start with `_` are internal.
`Role.bind`, `Profile.bind`, bound auth objects, and the auth protocols are
executor internals. `Profile.profile_name(account)` is supported for resolving
a configured profile name without authenticating; it runs a custom resolver
on the calling thread when invoked directly.

## Compatibility

During 0.x, intentional behavior changes require a minor release and explicit
migration notes. Starting with 1.0, patch releases contain compatible fixes;
minor releases may add compatible features or deprecations; incompatible API
or documented behavior changes require a major release. Deprecated public names
remain available throughout the current major version. Removing a supported
Python minor version also requires a major release after 1.0.

New export keys may be added in minor releases; consumers should read needed
keys rather than reject unknown keys. Existing keys and meanings remain stable
within a major version. Internal implementation, log wording, completion order
among simultaneous tasks, and performance measurements are not compatibility
guarantees. See [the 1.0 readiness record](readiness-1.0.md).
