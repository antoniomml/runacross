from __future__ import annotations

from io import StringIO

from runacross import (
    Account,
    AccountRegion,
    AccountRegionResult,
    AccountResult,
    ExecutionPhase,
    show_progress,
)


def test_show_progress_rewrites_one_line_when_enabled() -> None:
    stream = StringIO()
    on_result = show_progress(file=stream, disable=False)
    success = AccountResult(
        account=Account(id="111111111111"),
        value="ok",
        error=None,
        duration_seconds=0.1,
        phase=None,
    )
    failed = AccountResult[str](
        account=Account(id="222222222222"),
        value=None,
        error=RuntimeError("denied"),
        duration_seconds=0.1,
        phase=ExecutionPhase.AUTH,
    )
    worker = AccountResult[str](
        account=Account(id="333333333333"),
        value=None,
        error=RuntimeError("boom"),
        duration_seconds=0.1,
        phase=ExecutionPhase.WORKER,
    )

    on_result(success, completed=1, total=3)
    on_result(failed, completed=2, total=3)
    on_result(worker, completed=3, total=3)

    output = stream.getvalue()
    assert output.startswith("\r")
    assert output.endswith("\n")
    assert "1/3  ok 1  auth 0  worker 0  111111111111" in output
    assert "2/3  ok 1  auth 1  worker 0  222222222222" in output
    assert "3/3  ok 1  auth 1  worker 1  333333333333" in output


def test_show_progress_includes_region_and_stays_silent_by_default() -> None:
    stream = StringIO()
    silent = show_progress(file=stream)
    visible = show_progress(file=stream, disable=False)
    result = AccountRegionResult(
        target=AccountRegion(account=Account(id="111111111111"), region="eu-west-1"),
        value="ok",
        error=None,
        duration_seconds=0.1,
        phase=None,
    )

    silent(result, completed=1, total=1)
    assert stream.getvalue() == ""

    visible(result, completed=1, total=1)
    assert "111111111111 eu-west-1" in stream.getvalue()

    unknown = show_progress(file=stream, disable=False)
    unknown(object(), completed=1, total=1)
    assert "worker 1  -" in stream.getvalue()
