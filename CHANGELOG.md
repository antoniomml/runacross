# Changelog

All notable changes to RunAcross will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Initial `Account`, `AccountResult`, and `RunResults` models.
- Concurrent account execution through `map_accounts`.
- STS AssumeRole and isolated Boto3 Sessions.
- Per-account error phases, durations, and DEBUG logging.
- Optional active-account discovery through AWS Organizations.
- Python 3.10-3.14 support, tests, documentation, and CI.

