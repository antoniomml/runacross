# RunAcross roadmap

The roadmap records likely directions, not release dates or commitments.
Features should be added only when they preserve the small execution primitive.

The default path stays two calls and a callback:

```python
accounts = list_accounts(...)
results = map_accounts(callback, accounts=accounts, auth=...)
```

Extra capability should appear beside that shape, not inside `map_accounts`.

## 0.1

- Explicit account IDs and `Account` objects.
- STS AssumeRole and one authenticated Boto3 Session per account.
- Concurrent callback execution with a configurable worker limit.
- Typed, ordered, structured results and per-account error isolation.
- Basic DEBUG logging and duration measurements.
- Optional AWS Organizations discovery with an organization ID safety guard.
- Tests, typing, documentation, packaging, and CI.

## 0.2

- Pluggable authentication: `Role` (AssumeRole) and `Profile` (named AWS CLI /
  IAM Identity Center profiles), with `role_name=` kept as a `Role` shortcut.
- Authentication failure phase renamed from `assume_role` to `auth`.
- Explicit account-by-Region execution through `map_account_regions`.
- Enabled-Region discovery through Account Management `ListRegions`.
- Small account and Region exclude filters.
- A structured `AccountRegion` result identity for each account and Region pair.

## 0.3

- Explicit local account discovery from Identity Center profiles, scoped to
  one named SSO session with an optional organization guard.
- Eager validation of profile credentials so initial credential-provider
  failures are classified as authentication failures.

## 0.3.1

- Minimal executable examples for Identity Center, AssumeRole, Organizations,
  account-by-Region execution, and result export.
- Documented difference between local profile discovery and Organizations
  inventory.
- Documented public API surface.
- Result conversion: `to_dicts()`, `summary()`, `failures_by_phase()`, and
  `error_code`, without imposing a CLI or output format.

## 0.4

- `on_result` reports each target as it finishes, while the returned
  collection stays in input order.
- `show_progress()` rewrites one stderr status line on a TTY and stays
  silent otherwise. No tqdm or rich dependency.
- `limit=` on both `list_accounts` helpers so examples and dry runs can cap
  the discovered set without slicing.

## 0.5

- Optional `Profile(..., verify_account_id=True)` so
  `sts:GetCallerIdentity` must match the expected account ID.
- `profile_name` and `role_name` on each result, without credentials.

## 0.6

- `ConfigError` and `RunAcrossError` for discovery and configuration
  failures. Per-target errors stay on the result object.
- `parent_id` on `organizations.list_accounts()` for a root or OU, with
  nested OUs included by default.

## Next

Optional APIs beside the default path. Suggested order:

1. Reusable account selection beside the executor for Organizations account
   tags, name, or regular expression. Do not add those parameters to
   `map_accounts`.
2. Timeouts and deadlines only with honest semantics: Python threads cannot
   cancel an in-flight AWS call. Prefer marking unfinished work as failed
   over pretending the worker stopped.

Still deferred: callback retries, lifecycle hook triplets, `map_profiles()`,
and any built-in CLI.

## Later

Stability work that should land before much larger abstractions:

- Integration tests against simulated Identity Center profiles.
- Continued Python 3.10-3.14 compatibility in CI.
- Changelog migration examples when public names change.
- Stronger typing around generic callbacks.

Candidates that still need evidence from real usage:

- A configurable role ARN resolver.
- Additional STS session parameters.

RunAcross does not plan to become a CLI, scanner, policy engine, distributed
workflow system, credential store, or infrastructure deployment framework.
