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
mypy src/
python -m pip_audit
```

Tests must not require real AWS credentials or make live AWS calls. Prefer
small fakes, `unittest.mock`, or Botocore `Stubber`.

Open a pull request against `main`. Direct pushes, force pushes, and branch
deletion are blocked. CI must pass before a pull request can be merged.

PyPI uploads use GitHub Actions trusted publishing. Creating a GitHub Release
whose tag is `v` plus the version in `pyproject.toml` publishes that version.
The Publish workflow no longer accepts `workflow_dispatch`, and it does not
skip an existing PyPI version. The `pypi` GitHub Environment only allows
deployments from tags matching `v*`.

Before submitting a change:

- add tests for behavior changes;
- update user-facing documentation when the API changes;
- avoid new runtime dependencies unless the standard library is insufficient;
- do not include credentials, `.env` files, generated artifacts, or IDE state.

Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.

