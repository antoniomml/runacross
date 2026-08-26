# Changelog

All notable changes to RunAcross will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-08-26

### Added

- `ConfigError` and `RunAcrossError` for discovery and configuration
  failures. Per-target authentication and callback errors stay on result
  objects.
- `parent_id` on `organizations.list_accounts()` to list ACTIVE accounts
  under a root or OU. Nested OUs are included by default;
  `include_nested=False` keeps only direct children.

### Changed

- Account and Region discovery helpers raise `ConfigError` instead of
  `ValueError` or `RuntimeError` when configuration or inventory data
  cannot be used. `TypeError` is unchanged. AWS `ClientError` responses
  are not wrapped.

## [0.5.0] - 2026-08-26

### Added

- Optional `Profile(..., verify_account_id=True)` to confirm
  `sts:GetCallerIdentity` matches the expected account ID.
- `profile_name` and `role_name` on per-target results and in `to_dict()`
  output, without credentials.

## [0.4.0] - 2026-08-26

### Added

- `on_result` on `map_accounts` and `map_account_regions` to observe each
  target as it finishes. The returned collection stays in input order.
- `show_progress()` for a single TTY status line on stderr. Non-TTY streams
  stay silent. This is not a tqdm or rich dependency.
- `limit=` on `profiles.list_accounts()` and `organizations.list_accounts()`.

## [0.3.1] - 2026-08-26

### Added

- `to_dict()`, `to_dicts()`, `summary()`, and `failures_by_phase()` on
  execution results, for JSON, CSV, logging, or reports without imposing an
  output format.
- `error_code` on per-target results, taken from Botocore
  `ClientError.response["Error"]["Code"]`.
- Minimal examples for AssumeRole, Identity Center profiles, Organizations
  discovery, account-by-Region execution, and result export.
- Account-source comparison and a documented public API surface.

## [0.3.0] - 2026-08-26

### Added

- `runacross.profiles.list_accounts()` for local Identity Center account
  discovery scoped to one named SSO session, with an optional
  `DescribeOrganization` safety guard.

### Fixed

- `Profile` now resolves its lazy Boto3 credentials before starting a callback,
  so expired Identity Center tokens and denied role credentials are reported in
  the `auth` phase instead of the `worker` phase.

## [0.2.0] - 2026-08-21

### Added

- `Role` and `Profile` authentication. `Role` assumes an IAM role in each
  account; `Profile` uses named AWS CLI / IAM Identity Center profiles.
- `map_account_regions` for explicit account-by-Region execution.
- `AccountRegion`, `AccountRegionResult`, and `RegionResults`.
- `list_enabled_regions()` using Account Management `ListRegions`.
- `exclude_accounts` on both executors and `exclude_regions` on
  `map_account_regions`.
- `discover_regions=True` to expand each account to its enabled Regions.
- Identity Center profile example.

### Changed

- Authentication failures now use `ExecutionPhase.AUTH` (`"auth"`). The 0.1
  name `assume_role` is no longer emitted.
- `map_accounts` accepts `auth=` as the primary way to choose Role or Profile.
  `role_name=` remains as a shortcut for `Role`.
- Package description covers accounts and Regions.

## [0.1.2] - 2026-08-20

### Added

- GitHub Actions trusted publishing to PyPI.
- Optional `duration_seconds` for STS AssumeRole (900-43200).
- `runacross.__version__`.
- Organizations discovery example.
- Coverage reporting and `pip-audit` in CI.

### Changed

- Publish only from GitHub Release tags that match the package version.
- Publishing fails if that version already exists on PyPI.

### Fixed

- `Account.__repr__` redacts Organizations email addresses.
- `map_accounts` rejects a source Session with no Region before calling STS.

## [0.1.0] - 2026-08-20

### Added

- Initial `Account`, `AccountResult`, and `RunResults` models.
- Concurrent account execution through `map_accounts`.
- STS AssumeRole and isolated Boto3 Sessions.
- Per-account error phases, durations, and DEBUG logging.
- Optional active-account discovery through AWS Organizations.
- Python 3.10-3.14 support, tests, documentation, and CI.

### Fixed

- Constructing subscripted `AccountResult[T](...)` on Python 3.10.

[Unreleased]: https://github.com/antoniomml/runacross/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/antoniomml/runacross/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/antoniomml/runacross/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/antoniomml/runacross/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/antoniomml/runacross/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/antoniomml/runacross/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/antoniomml/runacross/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/antoniomml/runacross/compare/v0.1.0...v0.1.2
[0.1.0]: https://github.com/antoniomml/runacross/releases/tag/v0.1.0
