## Summary

- Describe the problem and the smallest useful change.

## Verification

- [ ] `pytest --cov=runacross --cov-report=term-missing --cov-fail-under=90`
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `mypy src/`
- [ ] `python -m pip_audit`
- [ ] Documentation updated when behavior changed

## Security

- [ ] No credentials, tokens, `.env` files, or sensitive AWS data included

