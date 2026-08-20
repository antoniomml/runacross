# Contributing to RunAcross

RunAcross favors small, explicit changes that keep the public API easy to
understand.

## Development setup

```bash
git clone <repository-url>
cd runacross
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the complete local checks:

```bash
pytest
ruff check .
ruff format --check .
mypy src/
```

Tests must not require real AWS credentials or make live AWS calls. Prefer
small fakes, `unittest.mock`, or Botocore `Stubber`.

Before submitting a change:

- add tests for behavior changes;
- update user-facing documentation when the API changes;
- avoid new runtime dependencies unless the standard library is insufficient;
- do not include credentials, `.env` files, generated artifacts, or IDE state.

