# 1.0 candidate validation kit

Stable 1.0 requires live consumer evidence for both authentication strategies,
reviewed by their owner ([readiness record](../docs/readiness-1.0.md)). This
directory provides two read-only scripts that produce a reproducible baseline
report when no downstream consumer script is available yet. Real consumer
scripts remain the preferred evidence.

## Safety

- The scripts perform only read-only calls: `sts:GetCallerIdentity` and, when
  requested, Account Management `ListRegions`. They never create, modify, or
  delete AWS resources.
- Use disposable or read-only target accounts. `--expect-failure` still calls
  `sts:AssumeRole`; a denied assumption changes nothing.
- Reports contain account IDs, ARNs, and profile names. Treat them as
  sensitive data and do not attach them to public issues.
- Run from an editable or installed environment: `python -m pip install -e
  ".[dev]"` or a released wheel. Never wire these scripts into CI or unit
  tests; the offline suite must stay offline.

## Prerequisites

Role:

- Source identity allowed to call `sts:AssumeRole` on the target role ARNs.
- Target role trust policy allowing the source identity, with
  `--external-id` when the trust policy requires one.
- `account:ListRegions` on the target role only for `--discover-regions`.

Profile:

- Named AWS CLI or IAM Identity Center profiles resolving to each target
  account, with a Region configured (`region = ...`) or
  `AWS_DEFAULT_REGION` exported.
- `aws sso login` completed for Identity Center profiles; RunAcross never
  runs a login flow.
- `--verify-account-id` uses `sts:GetCallerIdentity`, which needs no
  additional permission.

## Role run

```bash
python validation/role_consumer.py \
    --account 111111111111 \
    --account 222222222222 \
    --role-name SecurityAuditRole \
    --source-profile security \
    --region eu-west-1 \
    --regions eu-west-1,us-east-1 \
    --discover-regions \
    --expect-failure 999999999999 \
    --report role-report.json
```

The script runs `map_accounts`, then `map_account_regions` with the requested
Regions, then enabled-Region discovery when `--discover-regions` is present.
Drop the options you do not need. `--expect-failure` marks accounts that must
fail in `phase="auth"` while other targets keep running.

## Profile run

Explicit accounts:

```bash
python validation/profile_consumer.py \
    --account 111111111111 \
    --account 222222222222 \
    --pattern 'AWS-Infosec-{account_id}' \
    --verify-account-id \
    --regions eu-west-1 \
    --report profile-report.json
```

Mapping instead of a pattern:

```bash
python validation/profile_consumer.py \
    --account 111111111111 \
    --mapping-json '{"111111111111": "prod-security"}' \
    --report profile-report.json
```

Local Identity Center discovery:

```bash
python validation/profile_consumer.py \
    --sso-session control-tower \
    --pattern 'AWS-Infosec-{account_id}' \
    --limit 3 \
    --report profile-discovery-report.json
```

`--pattern` uses the same rules as the executor: `{account_id}` and, when the
`Account` object has a name, `{name}`, without format specifications or
conversions. This kit supplies account IDs without names (both `--account` and
`profiles.list_accounts`), so validate `{name}` patterns with `Account`
objects from another source, such as `organizations.list_accounts()`, in your
own script.

## Reading the result

Exit code `0` means every target matched: the STS identity belonged to the
target account, the Session used the requested Region, `role_name` or
`profile_name` metadata was correct, and expected authentication failures
stayed in `phase="auth"`. Anything else prints `VALIDATION FAILED` with one
line per problem and exits `1`.

The JSON report contains the environment (`runacross`, Python, boto3, and
botocore versions), per-target records, the summaries, and the problems list.

## Evidence checklist

Record one entry in the candidate validation table per reviewed run:

- [ ] Candidate version (`runacross` in the report) matches the tested release.
- [ ] Environment (Python, boto3, botocore) recorded in the report.
- [ ] Role run: every target returned `sts:GetCallerIdentity` for its own
      account and input order was preserved.
- [ ] Role run: expected authentication failures stayed in `phase="auth"` and
      did not cancel other targets.
- [ ] Region run: every Session used the requested Region
      (`value["region"]` in the report).
- [ ] Profile run: `result.profile_name` matched the resolved profile and
      `--verify-account-id` passed when used.
- [ ] Profile discovery run (when used): `profiles.list_accounts` returned the
      expected configured accounts.
- [ ] Reports saved in a private location and reviewed by the consumer owner.
- [ ] Any contract change needed is recorded as a finding and fixed before
      stable 1.0.

## Recording results

Add one row per run to the candidate validation record in
[`docs/readiness-1.0.md`](../docs/readiness-1.0.md).
