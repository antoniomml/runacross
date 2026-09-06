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

## 0.7 stabilization

- Reject async callbacks, observers and resolvers, including asynchronous
  returns hidden behind synchronous wrappers.
- Validate callable signatures and document the public error/ordering contract.
- Add `ResultCallback` and downstream typing checks.
- Exercise real SDK clients, paginators and Identity Center credential providers
  with simulated responses and no live AWS requests.
- Validate realistic paginated work with partial failures and record the
  concurrency/memory tradeoff.

## Next: 1.0 candidate

Stability takes priority over more selectors or execution modes. The
[September 2026 audit](audit-2026-09.md) records the evidence and tradeoffs.

The technical stabilization gates are covered in 0.7. Publish an opt-in
candidate after release validation and gather downstream Role/Profile script
evidence before stable 1.0. The [readiness record](readiness-1.0.md) defines the
acceptance criteria; there is no feature expansion required to reach 1.0.

## 0.6.1 maintenance

- Correct profile resolver identity and error isolation, and zero discovery limits.
- Bound pending futures and cancel queued work when execution is interrupted.
- Remove automatic exception logging and clear grouped exception tracebacks.
- Gate releases on CI and test Windows and the minimum supported Boto3.
- Isolate unit tests from local AWS credentials and live SDK requests.
- Publish an operations guide, benchmark, and prioritized audit report.

Still deferred: callback retries, lifecycle hook triplets, `map_profiles()`,
and any built-in CLI.

## Later

Candidates that still need evidence from real usage:

- A configurable role ARN resolver.
- Additional STS session parameters.
- Reusable Organizations selectors for account tags, names, or patterns,
  beside the executor rather than new executor parameters.
- Credential refresh or streaming results for runs that demonstrably need them.

Hard thread timeouts remain out of scope: marking a callback failed does not
stop it or undo its AWS side effects. Any future deadline API must account
for that explicitly.

RunAcross does not plan to become a CLI, scanner, policy engine, distributed
workflow system, credential store, or infrastructure deployment framework.
