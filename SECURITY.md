# Security policy

RunAcross handles temporary AWS credentials in memory and may be used with
privileged cross-account roles. Security reports should be treated carefully.

## Reporting a vulnerability

Do not include credentials, tokens, account email addresses, or other sensitive
AWS data in a public issue.

Before the repository is published, a private reporting channel must be
configured. GitHub Private Vulnerability Reporting is the preferred channel
when it is enabled for the repository. Until a private channel exists, do not
publish a report containing exploit details or sensitive data.

The project does not currently publish a security email address. No address
should be inferred from package metadata or contributor profiles.

## Security properties

RunAcross is designed to:

- use Boto3's existing credential provider chain;
- keep assumed credentials in memory only;
- avoid returning or deliberately logging STS credentials;
- create no credential files, credential caches, analytics, or telemetry;
- create only AWS service clients in the library itself;
- perform no AWS operation beyond role assumption and explicitly requested
  Organizations discovery unless the user's callback performs it.

The standard Boto3 provider chain may read local AWS configuration, use IAM
Identity Center caches, or execute a configured `credential_process`.
Callbacks are arbitrary user code and may access other services. Callback
exception messages are included in DEBUG logs, so applications must not place
credentials or secrets in exception text.

Applications remain responsible for least-privilege source and target IAM
policies, target-role trust policies, dependency updates, logging
configuration, and safe handling of callback results and exceptions.

