# Readiness for RunAcross 1.0

Decision date: September 6, 2026. The 0.7.0 stabilization work supports a
release candidate, not an immediate stable 1.0 declaration. A candidate is
an invitation to validate the proposed contract in downstream scripts.

Update (September 15, 2026): `1.0.0rc2` applies the follow-up audit hardening
fixes and stricter validation to the candidate runtime. The stable 1.0 gates
below are unchanged and still unmet.

The proposed `1.0.0rc1` contains the same runtime source, tests and dependency
requirements as 0.7.0. Only package version and release documentation change.
The candidate must pass the release workflow and public-install verification
independently; it is not the default installation and is not stable 1.0.

## Scope to freeze

The [public API contract](api.md) covers the two synchronous executors, Role
and Profile authentication, explicit discovery helpers, ordered results, result
conversion, and optional progress reporting. Keep one runtime dependency:
Boto3. There is no requirement for a CLI, async engine, streaming API, automatic
callback retry, automatic Role credential refresh, or new selector language.

## Technical gates

| Gate | Evidence in 0.7.0 |
| --- | --- |
| No false success for asynchronous work | Preflight checks cover async functions, callable objects, generators and partials. Runtime checks cover decorated returns and custom awaitables. Workers, resolvers and observers have explicit error behavior. |
| Stable input and error semantics | Documented signatures, duplicate/order behavior, empty selections, phases, validation types, observer cancellation and data-export rules; migration notes record stricter 0.7 behavior. |
| Useful downstream typing | `ResultCallback` describes positional results and keyword progress; mypy consumer fixtures verify return inference, covariance, and rejection of invalid calls. |
| Real SDK integration boundaries | 13 tests use actual clients, paginators, STS and modern Identity Center providers. Synthetic responses cover successful and denied authentication, expired SSO tokens, account verification, empty pages, nested OUs, limits, and regional inventory failures. |
| Compatibility and delivery | The full suite covers Python 3.10-3.14, Windows, and the exact minimum Boto3/Botocore. CI gates tagged releases; wheel/sdist and downstream installation are validated before release. |
| Representative offline behavior | Paginated inventory benchmark validates output ordering, partial failures, returned item counts, and one STS call per account while varying concurrency. |

## Recorded workload

`python benchmarks/inventory.py --latency-ms 50`, Python 3.14.7, Boto3 1.43.75,
macOS, median of three runs. Ten accounts, three Regions, three EC2 pages of
20 items each, 50 ms synthetic latency per page, and every seventh target
fails with `UnauthorizedOperation` on its last page. HTTP transport is blocked.
SDK clients are closed when their callbacks finish.

| Workers | Elapsed time | Peak traced Python memory | Success / failure | Returned instances | STS calls |
| ---: | ---: | ---: | --- | ---: | ---: |
| 1 | 12.1218 s | 257.8166 MiB | 26 / 4 | 1,560 | 10 |
| 10 | 7.8289 s | 429.0753 MiB | 26 / 4 | 1,560 | 10 |

These measurements include SDK Session/client/model setup and `tracemalloc`
overhead. They are not production latency, RSS, or AWS quota measurements.
More workers reduced this sample's elapsed time by about 35%, while increasing
peak traced memory by about 66%. With only 5 ms simulated latency, setup costs
dominated and ten workers did not improve elapsed time in an exploratory run.
Keep the current worker default and recommend tuning to actual service latency,
payload size and environment memory. Bounded futures do not imply bounded SDK
or result memory; small-memory Lambda functions should start with fewer workers.

## Candidate validation record

The [validation kit](../validation/README.md) runs read-only `Role` and
`Profile` consumer scripts against real accounts and writes a JSON report with
the environment, per-target records, and any detected problems. Record one row
per reviewed run; stable 1.0 requires both authentication strategies to be
present, green, and reviewed by the consumer's owner.

| Candidate | Auth | Operator | Date | Accounts / Regions | Result | Report |
| --- | --- | --- | --- | --- | --- | --- |
| 1.0.0rc2 | Role | _pending_ | | | | |
| 1.0.0rc2 | Profile | _pending_ | | | | |

A run passes when every target matched its account and Region, `role_name` or
`profile_name` metadata was correct, expected authentication failures stayed in
`phase="auth"` without cancelling other targets, and the owner reviewed the
report. Store reports privately; only link one here when it contains no
account data.

## Candidate and stable-release policy

After 0.7.0 passes its checks and installation verification, a release
candidate may freeze the proposed runtime API for opt-in downstream
validation. Publish candidates with the Python version spelling (for example
`1.0.0rc2`), a matching `v1.0.0rc2` tag, and the GitHub prerelease flag.
Normal installs should continue to select 0.7.0.

Stable 1.0 requires the following additional evidence:

1. At least one existing consumer script using Role and one using Profile are
   run against the candidate, with outcomes reviewed by their owner. Current
   offline integration tests cannot prove an organization's IAM trust policies,
   actual Identity Center assignments, or SDK behavior against live services.
   The [validation kit](../validation/README.md) is a reproducible baseline when
   no consumer script is available yet; record its results above.
2. Confirm no remaining known defect requires a public signature, error-phase,
   ordering or export-schema change. Fix compatible defects during the candidate
   period and rerun the relevant checks; issue a new candidate for contract changes.
3. Verify the candidate's public PyPI installation and retain a green matrix,
   dependency audit, packaging checks, and the release workflow on the exact tag.

There is no arbitrary waiting period or feature-count requirement, and no
promise of production validation without evidence. The known limitations
(synchronous threads, no forced cancellation, copied Role credential expiry,
SDK memory cost, and application-controlled result contents) remain documented
parts of the design rather than reasons to grow a framework before 1.0.

The versioning policy follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
1.0 defines the public API and subsequent incompatible changes require a major
version. Candidate releases do not make that stable guarantee yet.
