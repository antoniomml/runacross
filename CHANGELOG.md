# Changelog

All notable changes to RunAcross will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/antoniomml/runacross/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/antoniomml/runacross/compare/v0.1.0...v0.1.2
[0.1.0]: https://github.com/antoniomml/runacross/releases/tag/v0.1.0
