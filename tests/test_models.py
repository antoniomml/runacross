from __future__ import annotations

import pytest

from runacross import Account, AccountResult, ExecutionPhase, RunResults, __version__
from runacross.models import coerce_accounts


@pytest.mark.parametrize(
    "account_id",
    [
        "123",
        "abcdefghijkl",
        "\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\uff10\uff11\uff12",
        "12345678901a",
        "1234567890123",
    ],
)
def test_account_rejects_invalid_ids(account_id: str) -> None:
    with pytest.raises(ValueError, match="12 ASCII digits"):
        Account(id=account_id)


def test_account_accepts_valid_id_and_metadata() -> None:
    account = Account(
        id="123456789012",
        name="Production",
        email="aws@example.com",
    )

    assert account.id == "123456789012"
    assert account.name == "Production"
    assert account.email == "aws@example.com"


def test_account_repr_redacts_email() -> None:
    account = Account(
        id="123456789012",
        name="Production",
        email="aws@example.com",
    )

    text = repr(account)

    assert "aws@example.com" not in text
    assert "email=<redacted>" in text
    assert "Production" in text
    assert "123456789012" in text


def test_account_repr_omits_absent_email() -> None:
    assert "email" not in repr(Account(id="123456789012"))


def test_account_is_immutable() -> None:
    account = Account(id="123456789012")

    with pytest.raises(AttributeError):
        account.id = "999999999999"  # type: ignore[misc]


def test_coerce_accounts_accepts_ids_and_accounts() -> None:
    existing = Account(id="222222222222", name="Development")

    accounts = coerce_accounts(["111111111111", existing])

    assert accounts == (
        Account(id="111111111111"),
        existing,
    )


def test_coerce_accounts_rejects_a_single_string() -> None:
    with pytest.raises(TypeError, match="iterable"):
        coerce_accounts("111111111111")


def test_coerce_accounts_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError, match="index 1"):
        coerce_accounts(["111111111111", 42])  # type: ignore[list-item]


def test_account_result_success_can_contain_none() -> None:
    result: AccountResult[None] = AccountResult(
        account=Account(id="111111111111"),
        value=None,
        error=None,
        duration_seconds=0.5,
        phase=None,
    )

    assert result.success


def test_account_result_failure_requires_a_phase() -> None:
    with pytest.raises(ValueError, match="failure phase"):
        AccountResult[None](
            account=Account(id="111111111111"),
            value=None,
            error=RuntimeError("failed"),
            duration_seconds=0.5,
            phase=None,
        )


def test_account_result_failure_cannot_contain_a_value() -> None:
    with pytest.raises(ValueError, match="cannot also contain a value"):
        AccountResult(
            account=Account(id="111111111111"),
            value="contradictory",
            error=RuntimeError("failed"),
            duration_seconds=0.5,
            phase=ExecutionPhase.WORKER,
        )


def test_account_result_unwrap_returns_value_or_raises_error() -> None:
    successful = AccountResult(
        account=Account(id="111111111111"),
        value="value",
        error=None,
        duration_seconds=0.1,
        phase=None,
    )
    error = RuntimeError("failed")
    failed = AccountResult[str](
        account=Account(id="222222222222"),
        value=None,
        error=error,
        duration_seconds=0.1,
        phase=ExecutionPhase.WORKER,
    )

    assert successful.unwrap() == "value"
    with pytest.raises(RuntimeError, match="failed") as raised:
        failed.unwrap()
    assert raised.value is error


def test_run_results_exposes_ordered_subsets_and_counts() -> None:
    first = AccountResult(
        account=Account(id="111111111111"),
        value="first",
        error=None,
        duration_seconds=0.1,
        phase=None,
    )
    failed = AccountResult[str](
        account=Account(id="222222222222"),
        value=None,
        error=RuntimeError("failed"),
        duration_seconds=0.2,
        phase=ExecutionPhase.WORKER,
    )
    third = AccountResult(
        account=Account(id="333333333333"),
        value="third",
        error=None,
        duration_seconds=0.3,
        phase=None,
    )

    results = RunResults([first, failed, third])

    assert list(results) == [first, failed, third]
    assert results.successful == (first, third)
    assert results.failed == (failed,)
    assert results.success_count == 2
    assert results.failure_count == 1
    assert repr(results) == "RunResults(success_count=2, failure_count=1)"


def test_empty_run_results_is_valid() -> None:
    results: RunResults[str] = RunResults()

    assert list(results) == []
    assert results.success_count == 0
    assert results.failure_count == 0


def test_package_version_is_a_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__
