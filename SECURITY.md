# Security policy

RunAcross handles temporary AWS credentials in memory and may be used with
privileged cross-account roles. Security reports should be treated carefully.

## Reporting a vulnerability

Do not include credentials, tokens, account email addresses, or other sensitive
AWS data in a public issue.

Report vulnerabilities privately through
[GitHub Private Vulnerability Reporting](https://github.com/antoniomml/runacross/security/advisories/new).
Do not open a public issue for exploit details or sensitive data.

The project does not publish a security email address. No address should be
inferred from package metadata or contributor profiles.

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
`Profile` authenticates only through those named profiles; RunAcross does not
implement a separate login or profile-discovery mechanism.
Callbacks are arbitrary user code and may access other services. Callback
exception messages are included in DEBUG logs, so applications must not place
credentials or secrets in exception text.

`list_accounts()` copies account names and root email addresses returned by
AWS Organizations into `Account` objects. Treat those fields as sensitive:
do not log them at DEBUG, print them in shared output, or include them in
issues. `Account.__repr__` redacts `email` so accidental `print` or DEBUG
logging of the object does not expose the root address; the value is still
present on `account.email` for callers that need it.

Applications remain responsible for least-privilege source and target IAM
policies, target-role trust policies, dependency updates, logging
configuration, and safe handling of callback results and exceptions.

