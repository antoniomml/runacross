# Examples

Short, executable scripts for the main RunAcross paths. Replace account IDs,
role names, profile patterns, and organization IDs with your own values.

| Script | What it shows |
| --- | --- |
| [`caller_identity.py`](caller_identity.py) | AssumeRole into explicit accounts |
| [`identity_center_profiles.py`](identity_center_profiles.py) | Local Identity Center discovery plus `Profile` auth, `limit=`, `show_progress()`, and `verify_account_id` |
| [`organization_accounts.py`](organization_accounts.py) | Active-account discovery from AWS Organizations |
| [`ec2_inventory.py`](ec2_inventory.py) | One callback per account and Region |
| [`export_results.py`](export_results.py) | `summary()` and `to_dicts()` for JSON export |

`GetCallerIdentity` is used on purpose: it is a small callback that proves
authentication without extra AWS permissions beyond `sts:GetCallerIdentity`.
