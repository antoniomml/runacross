# AGENTS.md

## Cursor Cloud specific instructions

RunAcross is a pure Python library (no runnable service, server, or CLI). It
packages the AWS multi-account STS AssumeRole + concurrent execution pattern
behind `runacross.map_accounts`. "Running the app" means importing the library
and exercising `map_accounts`; "development" means the lint/type/test/build
checks.

### Environment

- The dev dependencies (`.venv` with `pip install -e ".[dev]"`) are refreshed by
  the startup update script. Activate the virtualenv before running any tool:
  `source .venv/bin/activate`.
- System Python is 3.12 (the library supports 3.10–3.14). CI runs the quality
  job on 3.14 and the test matrix on 3.10–3.14; locally 3.12 is fine. Creating a
  venv requires the `python3.12-venv` apt package, which is installed during
  setup (not part of the update script).

### Standard commands

See `CONTRIBUTING.md` and `.github/workflows/ci.yml` for the authoritative
command list. In short, from the repo root with the venv active:

- Tests: `pytest --cov=runacross --cov-report=term-missing --cov-fail-under=90`
- Lint: `ruff check .` and `ruff format --check .`
- Types: `mypy src/`
- Security: `python -m pip_audit`
- Build: `python -m build` then `python -m twine check dist/*`

### Non-obvious notes

- Tests MUST NOT require real AWS credentials or make live AWS calls; use fakes,
  `unittest.mock`, or botocore `Stubber` (see `tests/test_executor.py` for the
  `FakeStsClient`/`FakeSourceSession` pattern to demonstrate `map_accounts`
  without AWS).
- `map_accounts` requires the source session to have a region. Without a real
  AWS profile, pass a `source_session` (or set `AWS_DEFAULT_REGION`) or it raises
  `ValueError` before any STS call.
- `pip_audit` and `python -m build` reach out to the network (PyPI). They can be
  slow or fail in a restricted-egress environment; the offline checks are ruff,
  mypy, and pytest.
