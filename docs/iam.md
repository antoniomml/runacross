# IAM permissions

RunAcross uses the caller's existing AWS identity. With `Role`, that identity
assumes one IAM role in each target account. With `Profile`, each account is
reached through a named AWS CLI or IAM Identity Center profile, and no
cross-account `AssumeRole` is performed.

The examples below are starting points. Replace account IDs, partitions, role
names, and principals for the environment in which RunAcross is deployed.

## Source identity

When the target accounts and role name are known, grant only those role ARNs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeRunAcrossRoles",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::111111111111:role/SecurityAuditRole",
        "arn:aws:iam::222222222222:role/SecurityAuditRole"
      ]
    }
  ]
}
```

For a large organization with a consistently named role, the account segment
can be wildcarded while keeping the role name constrained:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeSecurityAuditRoleAcrossAccounts",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/SecurityAuditRole"
    }
  ]
}
```

Use `arn:aws-us-gov` or `arn:aws-cn` in the corresponding partition.

## Target role trust policy

Each target role must trust the specific source role or another deliberately
chosen principal:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustRunAcrossSourceRole",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::999999999999:role/RunAcrossSourceRole"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

When an external ID is required, add a condition and pass the same value to
`Role(..., external_id=...)` or `map_accounts(external_id=...)`:

```json
{
  "Condition": {
    "StringEquals": {
      "sts:ExternalId": "replace-with-a-managed-external-id"
    }
  }
}
```

External IDs help prevent confused-deputy attacks but are not credentials or
secrets. Keep their configuration consistent and never substitute them for a
restrictive trust policy.

## Target role permissions

The permissions policy on the target role depends entirely on the callback.
AWS does not require permission for `sts:GetCallerIdentity`, so the caller
identity example needs no additional target-role policy.

The EC2 inventory example calls `ec2:DescribeInstances`, which does not support
resource-level permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeInstances",
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*"
    }
  ]
}
```

Other callbacks should use service actions and resource ARNs as narrowly as
their AWS APIs permit.

## AWS Organizations discovery

Basic discovery needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListOrganizationAccounts",
      "Effect": "Allow",
      "Action": "organizations:ListAccounts",
      "Resource": "*"
    }
  ]
}
```

When `organization_id=` is supplied, the source also needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ValidateOrganization",
      "Effect": "Allow",
      "Action": "organizations:DescribeOrganization",
      "Resource": "*"
    }
  ]
}
```

These Organizations actions do not support resource-level permissions. The
caller must use the organization's management account or a member account
registered as a delegated administrator.

## Enabled-Region discovery

`list_enabled_regions()` and `map_account_regions(..., discover_regions=True)`
call Account Management `ListRegions` in the authenticated account:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListEnabledRegions",
      "Effect": "Allow",
      "Action": "account:ListRegions",
      "Resource": "*"
    }
  ]
}
```

Grant this on the assumed role when using `Role`, or on the Identity Center
permission set when using `Profile`.

## IAM Identity Center profiles

`Profile` does not call `sts:AssumeRole`. The Identity Center permission set
behind each profile needs the callback's service permissions, and
`account:ListRegions` if Region discovery is used.

When `Role` is used with an Identity Center **source** profile, the target
roles must trust that Identity Center role, for example:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustIdentityCenterSource",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::999999999999:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_SecurityAudit_0123456789abcdef"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Do not use `AWSReservedSSO_*` names as `Role.name`. Those roles typically
trust only the Identity Center service, not another principal's `AssumeRole`.
The source Identity Center role must still be allowed to call `sts:AssumeRole`
on the target role ARNs.

