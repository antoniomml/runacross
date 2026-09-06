from __future__ import annotations

from typing import Any

import pytest

from runacross import (
    Account,
    AccountRegion,
    AccountRegionResult,
    AccountResult,
    show_progress,
)


@pytest.mark.parametrize("regional", [False, True])
@pytest.mark.parametrize(
    "field,value,error_type,message",
    [
        ("duration_seconds", float("nan"), ValueError, "finite"),
        ("duration_seconds", float("inf"), ValueError, "finite"),
        ("duration_seconds", float("-inf"), ValueError, "finite"),
        ("duration_seconds", True, TypeError, "number"),
        ("duration_seconds", "1", TypeError, "number"),
        ("error", "failed", TypeError, "Exception"),
        ("error", KeyboardInterrupt(), TypeError, "Exception"),
        ("phase", "auth", TypeError, "ExecutionPhase"),
    ],
)
def test_invalid_result_fields_fail_at_construction(
    regional: bool, field: str, value: Any, error_type: type[Exception], message: str
) -> None:
    args = {"value": None, "error": None, "duration_seconds": 0.0, "phase": None}
    args[field] = value
    account = Account("111111111111")
    with pytest.raises(error_type, match=message):
        if regional:
            AccountRegionResult(target=AccountRegion(account, "eu-west-1"), **args)
        else:
            AccountResult(account=account, **args)


def test_account_result_requires_an_account_object() -> None:
    with pytest.raises(TypeError, match="account must be an Account"):
        AccountResult(
            account="111111111111",
            value=None,
            error=None,
            duration_seconds=0,
            phase=None,
        )


@pytest.mark.parametrize("disable", [0, 1, "yes"])
def test_progress_requires_an_explicit_bool_or_none(disable: Any) -> None:
    with pytest.raises(TypeError, match="disable must be a bool or None"):
        show_progress(disable=disable)
