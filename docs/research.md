# RunAcross research

This document records the product and technical validation performed before
implementing RunAcross 0.1.0. It reflects the Python, Boto3, Botocore, and AWS
documentation available on August 20, 2026.

## Product gap

RunAcross addresses a real and recurring pattern:

```text
accounts -> Role or Profile -> boto3 Session -> concurrent callback -> results
```

The pattern is useful, but it is not new. The closest existing projects are:

- [Botocove](https://github.com/connelldave/botocove) runs decorated Python
  functions concurrently across AWS accounts, organizational units, and
  regions. It handles role assumption and separates successful calls, worker
  exceptions, and AssumeRole failures. It is the closest functional match.
  Its public API is decorator-oriented, its output is a dictionary of loosely
  typed records, and its latest PyPI release found during this research was
  1.7.4 from November 2023.
- [awsrun](https://github.com/fidelity/awsrun) is an active CLI and Python
  framework for concurrent commands across AWS accounts and Azure
  subscriptions. It provides account loaders and credential providers, but
  library users implement command classes and interact with a broader plugin
  model.
- [orgcrawler](https://github.com/ucopacme/orgcrawler) executes Python payloads
  by account and region in AWS Organizations. The latest release found was a
  2020 beta.
- [Cloud Multi Query](https://github.com/ocadotechnology/cmq) runs chainable
  AWS resource queries across configured profiles. It is a query DSL and CLI,
  rather than an arbitrary callback runner based on a central AssumeRole.

Related tools solve different problems:

- Prowler and ScoutSuite are security scanners.
- Cloud Custodian is a policy and governance engine.
- Steampipe and CloudQuery query or synchronize cloud inventory.
- aws-vault, Granted, AWSume, boto3-assume, and aws-assume-role-lib manage
  credentials or individual assumed sessions.
- org-formation and similar tools manage AWS Organizations and infrastructure.
- Airflow, Prefect, Dagster, Celery, and Temporal are general orchestration
  systems requiring infrastructure and substantially more application code.

RunAcross therefore does not claim a unique execution mechanism. Its useful
gap is a small, maintained, permissively licensed library with:

- a direct function API instead of decorators, command classes, or plugins;
- explicit accounts, with Organizations kept as an optional source;
- typed, ordered, per-account and per-account-Region results;
- clear authentication versus callback failure phases;
- Role and Profile as parallel ways to obtain a Session;
- no CLI, scanner, policy language, scheduler, database, or infrastructure.

That is a differentiation in API quality and scope, not a new category.

## Name availability

The PyPI JSON endpoint for `runacross` returned 404 during this research, and
an exact GitHub repository-name search returned no result. The GitHub namespace
`github.com/runacross` is occupied, however, and RunAcross/RunAcrossUK is the
name of an active UK charity event. These checks neither reserve the package
name nor constitute trademark clearance. Availability and relevant trademark
registries must be checked again before publication.

## Concurrency and Boto3

[`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html)
is appropriate for the network-bound AWS SDK calls in this library. Its default
worker calculation is CPU-derived and has changed between Python releases, so
RunAcross uses an explicit, conservative default of 10 workers.

Boto3 documents
[`Session`](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/session.html)
and
[`Resource`](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/resources.html)
objects as not thread-safe. Low-level
[`Client`](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/clients.html)
objects are generally thread-safe if their metadata is not mutated and custom
Botocore event hooks do not alter that guarantee.

RunAcross consequently creates the source STS client before opening the pool,
shares only that client, and creates a new authenticated Session inside each
account task. The callback owns any clients or resources it creates from that
Session. It must not use the global `boto3.client()` shortcut concurrently.

## Credentials, STS, and Lambda

RunAcross relies on the standard
[Boto3 credential provider chain](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html).
This supports environment variables, profiles, IAM Identity Center, web
identity, ECS credentials, EC2 instance profiles, and Lambda execution roles
without introducing another credential store.

The current
[`AssumeRole` API](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html)
requires a `RoleSessionName` of 2-64 characters. `ExternalId` is optional and
accepts 2-1,224 characters. The default session duration is one hour; role
chaining is limited to one hour even when the target role allows longer
sessions. The STS quota is normally 600 requests per second per source account
and Region, shared with several other STS operations. Downstream service quotas
are often the practical limit.

Temporary credentials copied into a new Boto3 Session do not refresh
automatically. RunAcross therefore targets bounded callbacks that finish
within the assumed session lifetime. `Profile` uses IAM Identity Center or
other named profiles through Boto3 and does not implement a second login
flow.

AWS Lambda supplies execution-role credentials through the normal provider
chain. AWS recommends packaging the application's Boto3 dependency rather than
depending on the runtime copy. Threads must finish before the handler returns;
RunAcross does not keep a global executor or attempt background work across
invocations.

## Retries and throttling

Botocore provides `legacy`, `standard`, and `adaptive`
[retry modes](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html).
Legacy remains Boto3's compatibility default. Standard has broader,
cross-SDK retry behavior and defaults to three total attempts. Adaptive adds
experimental client-side rate limiting and can delay initial requests.

RunAcross uses standard mode with three total attempts for clients it owns.
Adaptive mode remains an explicit user choice. The callback creates its own
service clients, so it must pass its own `Config` when it needs non-default
retry behavior. RunAcross never retries the callback itself because an
arbitrary callback may not be idempotent.

Concurrency is controlled through `max_workers`. A large value is not expected
to scale linearly and can increase throttling, memory use, open connections,
and Lambda duration.

## AWS Organizations and Regions

[`ListAccounts`](https://docs.aws.amazon.com/organizations/latest/APIReference/API_ListAccounts.html)
must be called from the management account or a delegated administrator. It is
paginated, and AWS warns that a page can be empty while still returning a
`NextToken`; iteration only ends when the token is absent.

AWS Organizations account lifecycle values are now exposed through `State`:
`PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, `PENDING_CLOSURE`, and `CLOSED`.
The older `Status` field is scheduled for retirement on September 9, 2026.
RunAcross uses only `State` and includes only `ACTIVE` accounts by default.

An organization ID does not select an arbitrary organization. The caller's
credentials determine the organization. RunAcross can optionally compare an
expected `o-...` ID with `DescribeOrganization` before listing accounts, which
acts as a safety guard.

Multi-Region execution uses `map_account_regions`. Region discovery uses
Account Management `ListRegions`, treating `ENABLED` and `ENABLED_BY_DEFAULT`
as usable. Boto3 endpoint metadata alone does not describe which Regions an
account has enabled.

