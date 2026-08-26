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
    ExecutionPhase,
    Profile,
    RegionResults,
    Role,
    RunResults,
    __version__,
    map_account_regions,
    map_accounts,
)
```

`runacross.__all__` is the authoritative top-level list. These submodule
functions are also public:

- `runacross.profiles.list_accounts`
- `runacross.organizations.list_accounts`
- `runacross.regions.list_enabled_regions`

## Result conversion

`AccountResult` and `AccountRegionResult` expose `success`, `unwrap()`,
`phase`, `error_code`, and `to_dict()`. `error_code` is the Botocore
`ClientError` code at `response["Error"]["Code"]` when that value exists.

`RunResults` and `RegionResults` also expose `successful`, `failed`,
`success_count`, `failure_count`, `to_dicts()`, `failures_by_phase()`, and
`summary()`.

These helpers convert data. They do not print, write files, or choose a
report format. Serialized records include account IDs and optional names.
They omit Organizations email addresses and never include credentials.

## Internal

Do not depend on `runacross.sts`, `runacross.executor`, `runacross.auth`
names other than `Role` and `Profile`, or `runacross.models` helpers that are
not re-exported. Names that start with `_` are internal.

## Compatibility

Additive public names may appear in minor or patch releases. Breaking changes
to public names require a changelog migration note. Deprecated names stay
available at least until the next major version.
