# Contributing to RunAcross

RunAcross favors small, explicit changes that keep the public API easy to
understand.

## Development setup

```bash
git clone https://github.com/antoniomml/runacross.git
cd runacross
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the complete local checks:

```bash
pytest --cov=runacross --cov-report=term-missing --cov-fail-under=90
ruff check .
ruff format --check .
mypy src/ tests/typing/
python -m pip_audit
```

Tests must not require real AWS credentials or make live AWS calls. Prefer
small fakes, `unittest.mock`, or Botocore `Stubber`.
The autouse fixture isolates local AWS configuration and credentials and
blocks Botocore HTTP transport. Do not bypass it to contact a real account.
For test-only development, install `.[test]`; CI covers Python 3.10-3.14,
Windows on 3.14, and the declared minimum Boto3/Botocore on Python 3.10.
`tests/integration/` exercises actual SDK clients, paginators, STS and Identity
Center providers with Stubber and synthetic configuration. It remains offline.
`tests/typing/` checks downstream inference and deliberately invalid usages;
its `type: ignore` lines are negative tests enforced by mypy's strict mode.

Measure executor overhead without AWS access:

```bash
python benchmarks/pool.py
python benchmarks/inventory.py --latency-ms 50
```

Package checks should use a fresh output directory so old releases cannot
be mistaken for the current build:

```bash
python -m build --outdir dist/check
python -m twine check dist/check/*
```

Open a pull request against `main`. The `main` branch blocks direct pushes,
force pushes, and deletion. CI must pass before a pull request can be merged.

PyPI uploads use GitHub Actions trusted publishing. Creating a GitHub Release
whose tag is `v` plus the version in `pyproject.toml` publishes that version.
The release commit must pass the reusable CI workflow before the publishing
job can run, including dependency audit and compatibility checks.
The Publish workflow no longer accepts `workflow_dispatch`, and it does not
skip an existing PyPI version. The `pypi` GitHub Environment only allows
deployments from tags matching `v*`.

For a release, update `pyproject.toml` and `CHANGELOG.md`, merge the pull
request after all checks pass, and create the matching GitHub Release from
the merged commit. Check the Publish workflow and install the new PyPI version
in a clean environment before considering the release complete. Do not move
an existing release tag or overwrite a published version.

For a candidate, use Python's prerelease spelling (for example `1.0.0rc1`)
in the package version and the matching `v1.0.0rc1` tag. Mark the GitHub release
as a prerelease. Publishing that release still runs CI and uploads to PyPI;
normal installations should continue to select the latest non-prerelease.
Verify both an exact candidate install and normal version selection.

Before submitting a change:

- add tests for behavior changes;
- update user-facing documentation when the API changes;
- treat only `runacross.__all__` and the documented `list_accounts` /
  `list_enabled_regions` submodule functions as public API;
- avoid new runtime dependencies unless the standard library is insufficient;
- do not include credentials, `.env` files, generated artifacts, or IDE state.

Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.
